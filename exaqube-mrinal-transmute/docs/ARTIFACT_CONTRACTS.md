# Artifact contract architecture

## Source of truth and generation flow

`backend/app/models/artifacts.py` owns the strict final-output Pydantic models. The artifact-generation prompt embeds `model_json_schema()` from the exact model registered for the requested target. The prompt requires JSON with only declared properties, all required properties, exact types and enum values, and no additional properties. The provider client currently sends chat messages without an OpenAI `response_format`/JSON-schema parameter; generation therefore uses portable prompt guidance and local Pydantic validation. Provider-specific structured output must not be enabled unless the configured provider/model compatibility is verified.

`backend/app/services/artifact_contracts.py` is the single registration point connecting target format, artifact model, artifact schema version, target-specific prompt guidance, native writer, and output validator. `ArtifactTransformationService.transform()` resolves and validates this registration before provider invocation. The same contract instance supplies the prompt schema, response parser, native writer and file validator. A missing or inconsistent registration raises `ArtifactContractConfigurationError`; no artifact is fabricated.

After response parsing, source references are resolved against the original DocumentIR. PPTX additionally validates planned slide IDs, element IDs, mapping placement, purpose/visual-guidance consistency, and mapped source references. The registered writer generates native bytes, the registered output validator reopens/checks the file, then `ArtifactStore` persists it. Download APIs serve the stored native file. Unknown artifact properties remain errors (`extra="forbid"`). Sanitized logs and the structured 502 error details include target, schema model/version, artifact prompt version, field path, Pydantic error type and category; they never include response text or prompt content.

## Contract matrix

| Target | Reader | Planning model / prompt | Final artifact model and prompt schema | Native writer / output validation | Persistence / download |
| --- | --- | --- | --- | --- | --- |
| PPTX | `pptx_reader.py` | `PPTXOutputStructure`, `transformation_v9` target guidance and exact slide/element destination correspondence | `PPTXArtifactContent`, schema version `1.0`, generated from its Pydantic model; artifact prompt `artifact_v6` | `pptx_writer.render_pptx`; reopens package, checks slides and visible content | `ArtifactStore`; native PPTX media type/download route |
| XLSX | `xlsx_reader.py` | `XLSXOutputStructure`, `transformation_v9` target guidance and exact worksheet/table/column destination correspondence | Not registered: no final artifact model | No native XLSX writer or output validator; preflight rejects before LLM invocation | No output is persisted; transformation API returns unsupported-target error |
| DOCX | `docx_reader.py` | `DOCXOutputStructure`, `transformation_v9`; destination/mapping checks happen on stored plan | `DOCXArtifactContent`, schema version `1.0`, generated from its Pydantic model; artifact prompt `artifact_v6` | `render_docx`; opens generated DOCX and requires nonempty document text | `ArtifactStore`; native DOCX media type/download route |
| MMD | `mmd_reader.py` | `MMDOutputStructure`, `transformation_v9` target guidance and exact node/edge destination correspondence | Not registered: no final artifact model | No native Mermaid writer or output validator; preflight rejects before LLM invocation | No output is persisted; transformation API returns unsupported-target error |
| HTML | `html_reader.py` | `HTMLOutputStructure`, `transformation_v9` target guidance and exact section/component destination correspondence | `HTMLArtifactContent`, schema version `1.0`, generated from its Pydantic model; artifact prompt `artifact_v6` | `render_html`; checks document/title/main/section structure and rejects executable scripts | `ArtifactStore`; `text/html` download route |

The source reader supports an input format; it does not imply that format is also an available output target. XLSX and MMD planning models are present, but their final artifact schemas and native writers are not. The registry deliberately excludes them, so a workflow cannot spend provider tokens and then fail because a writer is absent.

## Intentional planning-to-artifact mappings

Planning and artifact schemas represent different stages; plan objects are never parsed as final artifacts.

| Planning data | Final output handling |
| --- | --- |
| PPTX `slide_id`, title and `mapping_ids` | Explicitly represented on `PPTXArtifactSlide`; plan alignment checks IDs and mapping locations. Element IDs and mapping IDs are represented on the typed element variants. |
| PPTX slide `purpose` and `visual_guidance` | Optional typed fields on `PPTXArtifactSlide`; the writer preserves them in that slide's speaker notes. They are metadata/guidance and do not create unsupported visual objects. |
| PPTX element purpose and mapping formatting guidance | Prompt instructions for content generation; output element types and mapped source references are checked against the plan. They are not copied as undeclared element fields. |
| DOCX document/section/element purpose and destination mappings | Instructions for the final document title, section order, content and formatting. The final DOCX model contains its own title, sections, paragraphs, bullets, metrics, tables and source references; plan IDs are not blindly copied into it. |
| HTML page/section/component purpose and mapping instructions | Instructions for the final page title and semantic sections/content. The final HTML model declares its own supported section content; plan IDs are not blindly copied into it. |
| XLSX/MMD structures and mappings | Remain planning-only until target artifact schemas, native writers and output validators are implemented and registered together. |

Source references are validated against DocumentIR for all registered outputs. PPTX plan mapping identity/placement is additionally checked. DOCX and HTML preserve source references in their generated content, while their current final artifact models do not carry planning `mapping_id` values; strict plan-to-content mapping reconciliation for those formats remains a known gap.

## Versioning and cached data

Artifact schema versioning (`artifact_schema_version`, currently `1.0`) is independent of transformation planning prompt/schema versioning (`transformation_v9`) and artifact prompt versioning (`artifact_v6`). A change to the final artifact shape requires an artifact schema version increment and an artifact prompt version increment when prompt behavior changes. It does not invalidate a valid stored plan unless the planning contract itself changes.

Stored plans are planning instructions only. Every transformation reparses a newly generated response against the registered artifact schema, resolves its citations, runs target-specific plan alignment where implemented, renders native bytes and validates the output file. A plan is never treated as validated artifact content. Previously persisted output files remain downloadable; a schema change governs newly generated output, not retroactive validation or mutation of stored artifacts.

## Current limitations

- XLSX and MMD can be read and planned but cannot be rendered; preflight/API checks reject those output targets explicitly.
- DOCX and HTML do not yet perform the same final mapping-ID-to-output-element reconciliation that PPTX performs.
- The LLM client uses prompt-constrained JSON and strict local validation, not provider-native JSON-schema mode.
