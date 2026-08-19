"""Wildcard Composer — standalone prototype.

Renders inline under Generation in txt2img/img2img, the same place
sd-advanced-stylebox-and-wildcards does (a collapsed InputAccordion). Inside:
a single Category -> Item cascading picker (not one row per category — with
~23 categories and some (PRESET, OUTFIT, POSE...) running into the hundreds of
entries, a fixed row per category was too much on screen at once). Picking an
item and clicking the insert ToolButton writes the raw __wildcard__ token into
the native prompt textarea via a tiny client-side JS function; both dropdowns
then reset to empty so the next pick starts clean. sd-dynamic-prompts (already
installed) resolves the token at generation time exactly as it does today.

This extension has no process() hook and never reads p.all_prompts — insertion
is 100% client-side. It cannot affect sd-webui-prompt-studio-neo or
sd-dynamic-prompts even if disabled or removed.
"""

from __future__ import annotations

import gradio as gr

from modules import script_callbacks, scripts, shared
from modules.ui_components import InputAccordion, ToolButton

from wc_lib.categorize import all_category_names, categorize_all, save_override
from wc_lib.scan import scan_wildcards

EXTN_ID = "wildcard_composer"
FULL_TAXONOMY = all_category_names()

_cache = {"entries": [], "buckets": {}, "order": []}


def _refresh_cache():
    entries = scan_wildcards()
    buckets, order = categorize_all(entries)
    _cache["entries"] = entries
    _cache["buckets"] = buckets
    _cache["order"] = order
    return entries, buckets, order


def on_ui_settings():
    section = (EXTN_ID, "Wildcard Composer")
    shared.opts.add_option(
        f"{EXTN_ID}_categories",
        shared.OptionInfo(
            ",".join(FULL_TAXONOMY),
            "Full category taxonomy (comma-separated). Only categories that "
            "currently have at least one wildcard get a slot; requires "
            "reloading the UI after adding a brand new category name here.",
            section=section,
        ).needs_reload_ui(),
    )


script_callbacks.on_ui_settings(on_ui_settings)


class WildcardComposerScript(scripts.Script):
    def title(self):
        return "Wildcard Composer"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        _refresh_cache()
        # Which categories are selectable: only the non-empty ones, in rule
        # order. Captured once so it stays consistent for the rest of this
        # tab's lifetime (Gradio layout is static; a category that starts
        # empty won't be selectable until the UI is reloaded).
        slot_categories = list(_cache["order"])
        tabname = "img2img" if is_img2img else "txt2img"
        insert_js = "wcInsertWildcardI2I" if is_img2img else "wcInsertWildcardT2I"

        def _items_for(category):
            return sorted(e.name for e in _cache["buckets"].get(category, []))

        def _category_choices():
            return [(f"{c} ({len(_cache['buckets'].get(c, []))})", c) for c in slot_categories]

        with InputAccordion(False, label="Wildcard Composer") as enabled:
            with gr.Row(variant="compact"):
                refresh_btn = ToolButton(
                    "🔄", elem_id=f"wcc_refresh_{tabname}", tooltip="Re-scan the wildcards folder"
                )
                status = gr.Markdown(f"{len(_cache['entries'])} wildcards found.")

            with gr.Row(variant="compact"):
                category_picker = gr.Dropdown(
                    choices=_category_choices(),
                    label="Category",
                    elem_id=f"wcc_category_{tabname}",
                    allow_custom_value=False,
                    scale=3,
                )
                item_picker = gr.Dropdown(
                    choices=[],
                    label="Item",
                    elem_id=f"wcc_item_{tabname}",
                    allow_custom_value=False,
                    scale=6,
                )
                insert_btn = ToolButton("➕", elem_id=f"wcc_insert_{tabname}", tooltip="Insert into prompt")

            def on_category_change(category):
                return gr.Dropdown.update(choices=_items_for(category), value=None)

            category_picker.change(fn=on_category_change, inputs=[category_picker], outputs=[item_picker])

            # Client-side: write the __wildcard__ token straight into this
            # tab's own prompt textarea. Independent listener on the same
            # click as the one below — see do_insert()'s docstring.
            insert_btn.click(fn=None, inputs=[item_picker], outputs=[], _js=insert_js)

            def do_insert(category, item):
                if not category or not item:
                    return "Pick a category and an item first.", gr.Dropdown.update(), gr.Dropdown.update()
                # Reset both pickers to empty so the next pick starts clean —
                # the actual text insertion already happened client-side via
                # the sibling .click() listener above.
                return f"Inserted: {item}", gr.Dropdown.update(value=None), gr.Dropdown.update(
                    choices=[], value=None
                )

            insert_btn.click(
                fn=do_insert,
                inputs=[category_picker, item_picker],
                outputs=[status, category_picker, item_picker],
            )

            def do_refresh(current_category):
                _refresh_cache()
                note = f"{len(_cache['entries'])} wildcards found."
                new_categories = [c for c in _cache["order"] if c not in slot_categories]
                if new_categories:
                    note += f" New categories with no row yet (reload the UI): {', '.join(new_categories)}."
                category_update = gr.Dropdown.update(choices=_category_choices())
                item_update = (
                    gr.Dropdown.update(choices=_items_for(current_category))
                    if current_category
                    else gr.Dropdown.update()
                )
                return note, category_update, item_update

            refresh_btn.click(
                fn=do_refresh,
                inputs=[category_picker],
                outputs=[status, category_picker, item_picker],
            )

            if not is_img2img:
                with gr.Accordion("Categorize", open=False):
                    gr.HTML(
                        "<p style='font-size:12px;color:var(--body-text-color-subdued);'>"
                        "The automatic category is just a guess. Fix it here when it's wrong "
                        "or when it lands in Uncategorized.</p>"
                    )
                    with gr.Row(variant="compact"):
                        uncategorized_only = gr.Checkbox(value=True, label="Uncategorized only")
                        entry_dd = gr.Dropdown(
                            choices=sorted(e.name for e in _cache["buckets"].get("Uncategorized", [])),
                            label="Wildcard",
                            elem_id="wcc_cat_entry",
                        )
                        target_category_dd = gr.Dropdown(
                            choices=FULL_TAXONOMY,
                            label="Category",
                            allow_custom_value=True,
                            elem_id="wcc_cat_target",
                        )
                        save_btn = ToolButton("💾", tooltip="Save category")

                    def toggle_entry_choices(only_uncat):
                        names = sorted(
                            e.name
                            for e in (
                                _cache["buckets"].get("Uncategorized", [])
                                if only_uncat
                                else _cache["entries"]
                            )
                        )
                        return gr.Dropdown.update(choices=names)

                    uncategorized_only.change(
                        fn=toggle_entry_choices, inputs=[uncategorized_only], outputs=[entry_dd]
                    )

                    def do_save(entry_name, target_category, only_uncat, picker_category):
                        if not entry_name or not target_category:
                            return (
                                "Pick a wildcard and a category.",
                                gr.Dropdown.update(),
                                gr.Dropdown.update(),
                                gr.Dropdown.update(),
                            )
                        save_override(entry_name, target_category)
                        _refresh_cache()

                        note = f"'{entry_name}' -> {target_category}"
                        category_update = gr.Dropdown.update(choices=_category_choices())
                        # Keep the main picker's item list in sync only if it's
                        # currently showing the category that just changed.
                        item_update = (
                            gr.Dropdown.update(choices=_items_for(picker_category))
                            if picker_category == target_category
                            else gr.Dropdown.update()
                        )
                        if target_category not in slot_categories:
                            note += " (no row yet — reload the UI)"
                        entry_update = toggle_entry_choices(only_uncat)
                        return note, category_update, item_update, entry_update

                    save_btn.click(
                        fn=do_save,
                        inputs=[entry_dd, target_category_dd, uncategorized_only, category_picker],
                        outputs=[status, category_picker, item_picker, entry_dd],
                    )

        return [enabled]
