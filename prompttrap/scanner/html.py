"""HTML scanner: extracts visible text and detects hidden manipulation.

Detectors:
  * hidden elements via inline ``style`` and ``<style>`` blocks (display:none,
    visibility:hidden, opacity:0)
  * off-screen text (position:absolute with large negative offsets)
  * white / near-white text on a light background
  * tiny text (font-size below a threshold)
  * HTML comments containing prompt-like / encoded payloads
  * ``<meta>`` tag content containing prompt-like / encoded payloads
  * ``<title>`` text containing prompt-like / encoded payloads
  * ``alt`` / ``title`` attributes containing prompt-like / encoded payloads
  * general zero-width / base64 / prompt-like payloads in extracted text
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from prompttrap.scanner.base import BaseScanner, Issue, ScanResult
from prompttrap.scanner.txt import TXTScanner

# Font size (in px) at or below this is treated as invisible "tiny" text.
TINY_FONT_PX = 3.0

# Large negative offset (in px) that places text off-screen.
OFFSCREEN_THRESHOLD = 1000

# RGB components at or above this are considered near-white.
NEAR_WHITE_THRESHOLD = 0.9


class HTMLScanner(BaseScanner):
    name = "html"

    def scan(self, path: Path) -> ScanResult:
        path = Path(path)
        start = time.perf_counter()
        sha = self.sha256_of(path)
        size_bytes = path.stat().st_size
        raw_text = path.read_text(encoding="utf-8", errors="replace")

        soup = BeautifulSoup(raw_text, "lxml")

        # Parse <style> blocks into CSS rules for class/ID/element matching.
        css_rules = self._parse_style_blocks(soup)

        issues: list[Issue] = []
        extracted_parts: list[str] = []
        visible_parts: list[str] = []
        metadata: dict[str, Any] = {}

        # Extract <meta> and <title> into metadata and scan for payloads.
        issues.extend(self._scan_meta_tags(soup, metadata))
        issues.extend(self._scan_title(soup, metadata))

        # Walk the DOM, separating visible text from hidden text.
        issues.extend(
            self._walk_dom(soup, css_rules, extracted_parts, visible_parts)
        )

        # Scan HTML comments.
        issues.extend(self._scan_comments(soup))

        # Scan alt/title attributes.
        issues.extend(self._scan_alt_title(soup))

        extracted_text = "\n".join(p for p in extracted_parts if p).strip()
        visible_text = "\n".join(p for p in visible_parts if p).strip()

        # Re-use the general TXT detectors on the full machine-readable text.
        general = TXTScanner().scan_text(extracted_text)
        for issue in general.issues:
            if issue not in issues:
                issues.append(issue)

        elapsed_ms = (time.perf_counter() - start) * 1000
        return ScanResult(
            path=str(path),
            file_type=self.detect_type(path),
            sha256=sha,
            size_bytes=size_bytes,
            issues=issues,
            extracted_text=extracted_text,
            visible_text=visible_text,
            metadata=metadata,
            processing_time_ms=round(elapsed_ms, 3),
        )

    # ---- CSS resolution -------------------------------------------------

    def _parse_style_blocks(self, soup: Tag) -> list[tuple[str, dict[str, str]]]:
        """Extract CSS rules from ``<style>`` blocks using tinycss2.

        Returns a list of ``(selector_text, {property: value})`` tuples.
        Supports simple selectors: ``.class``, ``#id``, ``tag``, ``*``.
        """
        import tinycss2

        rules: list[tuple[str, dict[str, str]]] = []
        for style_tag in soup.find_all("style"):
            css = style_tag.get_text()
            if not css.strip():
                continue
            try:
                parsed = tinycss2.parse_stylesheet(
                    css, skip_comments=True, skip_whitespace=True
                )
            except Exception:
                continue
            for node in parsed:
                if node.type != "qualified-rule":
                    continue
                selector = tinycss2.serialize(node.prelude).strip()
                if not selector:
                    continue
                try:
                    declarations = tinycss2.parse_declaration_list(
                        node.content, skip_comments=True, skip_whitespace=True
                    )
                except Exception:
                    continue
                props: dict[str, str] = {}
                for decl in declarations:
                    if decl.type == "declaration":
                        props[decl.lower_name] = tinycss2.serialize(decl.value).strip().lower()
                if props:
                    rules.append((selector, props))
        return rules

    @staticmethod
    def _match_selector(selector: str, tag: Tag) -> bool:
        """Match a simple CSS selector (``.class``, ``#id``, ``tag``, ``*``)."""
        selector = selector.strip()
        if selector == "*":
            return True
        if selector.startswith("."):
            classes = tag.get("class", [])
            if isinstance(classes, str):
                classes = classes.split()
            return selector[1:] in classes
        if selector.startswith("#"):
            return tag.get("id") == selector[1:]
        # Tag name selector (handle compound like "div.hidden" by splitting).
        for part in selector.split(","):
            part = part.strip()
            if part == tag.name:
                return True
        return False

    @staticmethod
    def _css_rules_for_tag(tag: Tag, css_rules: list[tuple[str, dict[str, str]]]) -> dict[str, str]:
        """Return CSS properties from ``<style>`` rules that match ``tag``."""
        props: dict[str, str] = {}
        for selector, rule_props in css_rules:
            if HTMLScanner._match_selector(selector, tag):
                props.update(rule_props)
        return props

    @staticmethod
    def _computed_style(tag: Tag | None) -> dict[str, str]:
        """Parse inline ``style`` attribute into a property dict."""
        if tag is None:
            return {}
        style = tag.get("style", "")
        if not style:
            return {}
        props: dict[str, str] = {}
        for decl in style.split(";"):
            if ":" not in decl:
                continue
            key, val = decl.split(":", 1)
            props[key.strip().lower()] = val.strip().lower()
        return props

    def _effective_style(
        self, tag: Tag | None, css_rules: list[tuple[str, dict[str, str]]]
    ) -> dict[str, str]:
        """Compute effective CSS by walking ancestors then the tag itself.

        Inline styles override ``<style>`` block rules at the same level.
        Child properties override inherited ancestor properties.
        """
        if tag is None or not isinstance(tag, Tag):
            return {}
        styles: dict[str, str] = {}
        for ancestor in reversed(list(tag.parents)):
            if not isinstance(ancestor, Tag):
                continue
            styles.update(self._css_rules_for_tag(ancestor, css_rules))
            styles.update(self._computed_style(ancestor))
        styles.update(self._css_rules_for_tag(tag, css_rules))
        styles.update(self._computed_style(tag))
        return styles

    # ---- DOM walk -------------------------------------------------------

    def _walk_dom(
        self,
        soup: Tag,
        css_rules: list[tuple[str, dict[str, str]]],
        extracted: list[str],
        visible: list[str],
    ) -> list[Issue]:
        issues: list[Issue] = []
        # Track (code, id(tag)) to avoid duplicate issues for the same element.
        seen: set[tuple[str, int]] = set()

        for element in soup.descendants:
            if isinstance(element, NavigableString) and not isinstance(element, Comment):
                text = str(element)
                if not text.strip():
                    continue

                parent = element.parent
                parent_style = self._effective_style(parent, css_rules)

                extracted.append(text.strip())

                if self._is_visible_style(parent_style):
                    visible.append(text.strip())

                issues.extend(self._style_issues(parent_style, text, parent, seen))

        return issues

    @staticmethod
    def _is_visible_style(style: dict[str, str]) -> bool:
        if style.get("display") == "none":
            return False
        if style.get("visibility") == "hidden":
            return False
        opacity = style.get("opacity", "")
        if opacity:
            try:
                if float(opacity) <= 0:
                    return False
            except ValueError:
                pass
        color = HTMLScanner._parse_color(style.get("color", ""))
        bg = HTMLScanner._parse_color(style.get("background", "") or style.get("background-color", ""))
        if color and HTMLScanner._is_near_white(color) and (
            not bg or HTMLScanner._is_near_white(bg)
        ):
            return False
        font_size = HTMLScanner._parse_font_size(style.get("font-size", ""))
        if font_size is not None and font_size <= TINY_FONT_PX:
            return False
        if HTMLScanner._is_offscreen(style):
            return False
        return True

    def _style_issues(
        self,
        style: dict[str, str],
        text: str,
        parent: Tag | None,
        seen: set[tuple[str, int]],
    ) -> list[Issue]:
        out: list[Issue] = []
        if not text.strip():
            return out
        loc = {"tag": parent.name if parent else "?"}
        tag_id = id(parent) if parent else 0

        def _add(code: str, message: str) -> None:
            key = (code, tag_id)
            if key in seen:
                return
            seen.add(key)
            out.append(Issue(code=code, severity="high", message=message, evidence=text[:200], location=loc))

        if style.get("display") == "none":
            _add("ST-HTML-HIDDEN-DISPLAY", "Element hidden with display:none.")
        if style.get("visibility") == "hidden":
            _add("ST-HTML-HIDDEN-VISIBILITY", "Element hidden with visibility:hidden.")
        opacity = style.get("opacity", "")
        if opacity:
            try:
                if float(opacity) <= 0:
                    _add("ST-HTML-HIDDEN-OPACITY", "Element hidden with opacity:0.")
            except ValueError:
                pass

        color = self._parse_color(style.get("color", ""))
        if color and self._is_near_white(color):
            _add("ST-HTML-WHITE-TEXT", "White / near-white text invisible on light background.")

        font_size = self._parse_font_size(style.get("font-size", ""))
        if font_size is not None and font_size <= TINY_FONT_PX:
            _add("ST-HTML-TINY-TEXT", f"Tiny text (font-size {font_size}px) effectively invisible.")

        if self._is_offscreen(style):
            _add("ST-HTML-OFFSCREEN-TEXT", "Text positioned off-screen via large negative offsets.")

        return out

    @staticmethod
    def _is_offscreen(style: dict[str, str]) -> bool:
        if style.get("position") != "absolute":
            return False
        for prop in ("left", "top"):
            val = style.get(prop, "")
            m = re.match(r"^(-?\d+(?:\.\d+)?)", val)
            if m:
                try:
                    if float(m.group(1)) <= -OFFSCREEN_THRESHOLD:
                        return True
                except ValueError:
                    pass
        return False

    @staticmethod
    def _parse_color(val: str) -> tuple[float, float, float] | None:
        if not val:
            return None
        val = val.strip().lower()
        if val == "white":
            return (1.0, 1.0, 1.0)
        m = re.match(r"^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$", val)
        if m:
            return (int(m.group(1), 16) / 255, int(m.group(2), 16) / 255, int(m.group(3), 16) / 255)
        m = re.match(r"^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", val)
        if m:
            return (int(m.group(1)) / 255, int(m.group(2)) / 255, int(m.group(3)) / 255)
        return None

    @staticmethod
    def _is_near_white(color: tuple[float, float, float]) -> bool:
        return all(c >= NEAR_WHITE_THRESHOLD for c in color)

    @staticmethod
    def _parse_font_size(val: str) -> float | None:
        if not val:
            return None
        m = re.match(r"^(\d+(?:\.\d+)?)px", val.strip().lower())
        if m:
            return float(m.group(1))
        return None

    # ---- Metadata / comments / attributes ------------------------------

    def _scan_meta_tags(self, soup: Tag, metadata: dict[str, Any]) -> list[Issue]:
        issues: list[Issue] = []
        for i, meta in enumerate(soup.find_all("meta")):
            name = meta.get("name") or meta.get("property") or f"meta_{i}"
            content = meta.get("content", "")
            if content:
                metadata[name] = content
                general = TXTScanner().scan_text(content)
                if general.issues:
                    issues.append(
                        Issue(
                            code="ST-HTML-METADATA-PROMPT",
                            severity="high",
                            message=f"Prompt-like / encoded payload in <meta> tag '{name}'.",
                            evidence=content[:200],
                            location={"tag": "meta", "name": name},
                        )
                    )
        return issues

    def _scan_title(self, soup: Tag, metadata: dict[str, Any]) -> list[Issue]:
        issues: list[Issue] = []
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text()
            if title.strip():
                metadata["title"] = title.strip()
                general = TXTScanner().scan_text(title)
                if general.issues:
                    issues.append(
                        Issue(
                            code="ST-HTML-METADATA-PROMPT",
                            severity="high",
                            message="Prompt-like / encoded payload in <title> tag.",
                            evidence=title[:200],
                            location={"tag": "title"},
                        )
                    )
        return issues

    def _scan_comments(self, soup: Tag) -> list[Issue]:
        issues: list[Issue] = []
        for i, comment in enumerate(soup.find_all(string=lambda t: isinstance(t, Comment))):
            text = str(comment).strip()
            if not text:
                continue
            general = TXTScanner().scan_text(text)
            if general.issues:
                issues.append(
                    Issue(
                        code="ST-HTML-COMMENT-PROMPT",
                        severity="high",
                        message="Prompt-like / encoded payload found in an HTML comment.",
                        evidence=text[:200],
                        location={"comment_index": i},
                    )
                )
        return issues

    def _scan_alt_title(self, soup: Tag) -> list[Issue]:
        issues: list[Issue] = []
        for tag in soup.find_all(True):
            for attr in ("alt", "title"):
                val = tag.get(attr)
                if not val or not isinstance(val, str) or not val.strip():
                    continue
                general = TXTScanner().scan_text(val)
                if general.issues:
                    issues.append(
                        Issue(
                            code="ST-HTML-ALT-TEXT-PROMPT",
                            severity="high",
                            message=f"Prompt-like / encoded payload in '{attr}' attribute.",
                            evidence=val[:200],
                            location={"tag": tag.name, "attribute": attr},
                        )
                    )
        return issues
