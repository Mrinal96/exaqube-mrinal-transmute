# Artifact contract architecture

## Source of truth and generation flow

`backend/app/models/artifacts.py` owns the strict final-output Pydantic models. The artifact-generation prompt embeds `model_json_schema()` from the exact model registered for the requested target. The prompt requires JSON with only declared properties, all required properties, exact types and enum values, and no additional properties. The provider client currently sends chat messages without an OpenAI `response_format`/JSON-schema parameter; generation therefore uses portable prompt guidance and local Pydantic validation. Provider-specific structured output must not be enabled unless the configured provider/model compatibility is verified.

`backend/app/services/artifact_contracts.py` is the single registration point connecting target format, artifact model, artifact schema version, target-specific prompt guidance, native writer, and output validator. `ArtifactTransformationService.transform()` resolves and validates this registration before provider invocation. The same contract instance supplies the prompt schema, response parser, native writer and file validator. A missing or inconsistent registration raises `ArtifactContractConfigurationError`; no artifact is fabricated.

After response parsing, source references are resolved against the original DocumentIR. PPTX additionally validates planned slide IDs, element IDs, mapping placement, purpose/visual-guidance consistency, and mapped source references. The registered writer generates native bytes, the registered output validator reopens/checks the file, then `ArtifactStore` persists it. Download APIs serve the stored native file. Unknown artifact properties remain errors (`extra="forbid"`). Sanitized logs and the structured 502 error details include target, schema model/version, artifact prompt version, field path, Pydantic error type and category; they never include response text or prompt content.

## Contract matrix

| Target | Reader | Planning model / prompt | Final artifact model and prompt schema | Native writer / output validation | Persistence / download |
| --- | --- | --- | --- | --- | --- |
| PPTX | `pptx_reader.py` | `PPTXOutputStructure`, versioned transformation prompt and exact slide/element destination correspondence | `PPTXArtifactContent`, schema `1.2`, generated from its Pydantic model; artifact prompt `artifact_v8` | `pptx_writer.render_pptx`; reopens package, checks slides and visible content; planned IDs, mappings and source references are reconciled | `ArtifactStore`; native PPTX media type/download route |
| XLSX | `xlsx_reader.py` | XLSX planning schema exists, but its mappings are not applied by the writer | No LLM artifact schema; deterministic `DocumentIR` export contract `native-ir-xlsx-v1` | `xlsx_writer.render_xlsx`; reopens workbook, validates visible sheets, document metadata and worksheet bounds; table/formula overlaps are rejected | `ArtifactStore`; native XLSX media type/download route |
| DOCX | `docx_reader.py` | `DOCXOutputStructure`; mappings use section/element destinations | `DOCXArtifactContent`, schema `1.2`, generated from its Pydantic model; artifact prompt `artifact_v8` | `render_docx`; reopens generated DOCX and requires nonempty document text; planned section/element IDs, hierarchy, order, mappings and citations are reconciled before rendering | `ArtifactStore`; native DOCX media type/download route |
| MMD | `mmd_reader.py` | MMD planning schema exists, but its mappings are not applied by the writer | No LLM artifact schema; deterministic `DocumentIR` export contract `native-ir-mmd-v1` | `mmd_writer.render_mmd`; checks declaration, direction, control characters and subgraph balance. It does not validate the complete Mermaid grammar | `ArtifactStore`; Mermaid source download route |
| HTML | `html_reader.py` | `HTMLOutputStructure`; mapping destinations use section/component IDs | `HTMLArtifactContent`, schema `1.2`, generated from its Pydantic model; artifact prompt `artifact_v8` | `render_html`; checks document/title/main structure and rejects executable scripts; planned semantic tags, navigation, section/component IDs, ordering, mappings and citations are reconciled | `ArtifactStore`; `text/html` download route |

The source reader supports an input format; it does not imply semantic conversion to that same format. XLSX and MMD use deterministic IR-export contracts rather than the LLM artifact-contract registry. Their planning schemas are not consumed by those writers; the transformation service rejects plans and user instructions for these targets rather than silently ignoring them.

## Intentional planning-to-artifact mappings

Planning and artifact schemas represent different stages; plan objects are never parsed as final artifacts.

| Planning data | Final output handling |
| --- | --- |
| PPTX `slide_id`, title and `mapping_ids` | Explicitly represented on `PPTXArtifactSlide`; plan alignment checks IDs and mapping locations. Element IDs and mapping IDs are represented on the typed element variants. |
| PPTX slide `purpose` and `visual_guidance` | Optional typed fields on `PPTXArtifactSlide`; the writer preserves them in that slide's speaker notes. They are metadata/guidance and do not create unsupported visual objects. |
| PPTX element purpose and mapping formatting guidance | Prompt instructions for content generation; output element types and mapped source references are checked against the plan. They are not copied as undeclared element fields. |
| DOCX section/element IDs, heading levels, order and destination mappings | Represented by section and content-item IDs, mapping lists and element order in the artifact model; reconciled with the stored plan before native rendering. |
| HTML semantic elements, navigation, section/component IDs and mappings | Represented in the artifact model and DOM IDs; reconciled with the stored plan before rendering. Chart and link components remain in the planning schema but are explicitly rejected before artifact generation because their content is not represented by the HTML artifact model. |
| XLSX/MMD structures and mappings | Planning schemas are not consumed by the deterministic IR writers. These are native exports, not plan-driven semantic transformations. |

Source references are validated against DocumentIR for all LLM-generated outputs. PPTX, DOCX and HTML additionally reconcile mapping placement and source references against their plans before rendering. XLSX and MMD preserve source locations as IR export data and do not consume semantic plans.

## Versioning and cached data

Artifact schema versioning (`artifact_schema_version`, currently `1.2`) is independent of transformation planning prompt/schema versioning and artifact prompt versioning (`artifact_v8`). A change to the final artifact shape requires an artifact schema version increment and an artifact prompt version increment when prompt behavior changes. It does not invalidate a valid stored plan unless the planning contract itself changes.

Stored plans are planning instructions only. Every transformation reparses a newly generated response against the registered artifact schema, resolves its citations, runs target-specific plan alignment where implemented, renders native bytes and validates the output file. A plan is never treated as validated artifact content. Previously persisted output files remain downloadable; a schema change governs newly generated output, not retroactive validation or mutation of stored artifacts.

## Current limitations

- XLSX and MMD output is deterministic IR export; target plans and user transformation instructions are not applied.
- Mermaid output checks a subset of structural conditions only; it does not prove full Mermaid grammar validity because no parser/CLI is installed.
- The LLM client uses prompt-constrained JSON and strict local validation, not provider-native JSON-schema mode.
