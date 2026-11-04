# Seedance 导演方法

按当前任务只读相应步骤。提示词使用[本地Seedance格式](../../seedance-prompts/references/formats.md)；本文件英文示例用于解释导演方法，交付跟随用户语言与已采用格式。单镜复杂度建议不限制Seedance的多镜头叙事能力。

## Hard rules

1. **Story function first.** A shot with no story function is deleted, not improved.
2. **Blocking before framing.** Decide what bodies do in space, then place the camera. A well-blocked scene reads even shot flat.
3. **One dominant camera move and one primary event per shot.** No move at all is a legitimate choice and often the better one. Unrelated actions stacked into one clip is the same defect from the other side — the motion budget is owned by `ai-video-tool-adapters.md`.
4. **Every action has an end state.** "He turns" is not a shot. "He turns until his profile is against the window, then stops" is.
5. **Behavior, not emotion.** Never prompt "he is afraid." Prompt what fear looks like on a body.
6. **Continuity is engineered.** Separate fixed identity, era and geography from the current look and planned state changes. Keep adopted clauses consistent across shots; a wardrobe change uses its own look source. Describe persistent light sources in world space and derive their screen-side direction for each camera setup.
7. **Use the control point the mode actually exposes.** A first/last-frame workflow needs sound stills; a subject-reference workflow needs sound identity and appearance sources. Validate the selected inputs before spending video generations. New keyframes serve specific composition or action gaps, not every video by default.
8. **Match the tool's control surface.** Do not ask a model for a feature it does not expose. Identify the surface, then pick the prompt shape.
9. **Negatives are targeted, and they name instances.** Include only the constraints matching this shot's real risk. "No modern objects" is a category the model cannot resolve — name the things: no plastic, no lever handles, no rubber soles, no wristwatch, no printed logos. Long negative lists dilute and can invoke what they forbid.
10. **One style lens at a time.** Mixing two directors produces incoherence. Pick one, say why, note what the other would have given.
11. **Answer the size of the question.** A prompt request gets a prompt. Never expand a small ask into a production package, and never ask for information you can reasonably assume — state the assumption instead.

## Pipeline

Thirteen steps. Run only the ones the request needs, in this order. Each step names the file to load if you go deep.

### 1. Intake and scope

When defining a film’s elements, assigning reference/control responsibilities, or resolving conflicting inputs, use [element and control responsibilities](element-control-contract.md). Cover applicable elements internally, assign their adopted sources and actual controls, and carry the result in the existing brief or shot plan. Do not turn a small prompt request into a full production package.

Fix the deliverable, duration, aspect, tool, genre, and constraints. Identify the current input mode and existing assets before deciding what new images are needed; use Step 9's adapter reference here when that decision depends on tool capabilities. State assumptions in one or two lines, then work. Estimate the shot budget from target duration and pacing (`editing-and-assembly.md`); shot count is not an image or paid-task count.

### 2. Script and subtext breakdown

Identify, in this order:

- **Literal event** — what happens on the surface.
- **Dramatic question** — what the audience should be wondering.
- **Conflict** — external and internal.
- **Subtext** — what the scene is actually about.
- **Emotional movement** — opening emotion → pressure → turn → closing emotion.
- **Visual thesis** — the simplest visual idea that governs the scene.

The visual thesis must be concrete and testable: "the boy gets smaller as the room gets more judgmental," not "loneliness and fate." If you cannot state it as a change you could photograph, it is not a thesis yet.

**Non-narrative work skips this block.** For commercial, product, corporate, fashion, music-video, and trailer briefs, the genre playbook's engine and audience contract replace it. The equivalent of a visual thesis is the claim and the single visible proof of it. Do not derive subtext for a lipstick.

### 3. Beat map

Break the scene into beats, not shots. A beat is a change in the balance of pressure — not a change of camera. Each beat carries: story function, character state in and out, visual action, pressure delta, and a likely shot family drawn from the nine functions owned by `cinematic-language.md` — establishing, relation, close-up, insert/detail, reaction, transition, aftermath, point-of-view, reveal. Do not coin others; Step 7 has to look the word up.

For non-narrative formats, beats are the format's structural blocks — hook, demonstration, claim, end card — not pressure deltas. Template: `../assets/beat-sheet-template.md`.

### 4. Style lens selection (optional)

If the user names a director or says "in the style of X," load exactly one file from `director_styles/` and treat its `风格参数 / Style parameters` YAML as the override set for Steps 5, 7, 8, and 10. Step 8 matters most: the still is where a style is actually fixed, and a lens applied to the shot list but not to the keyframe will not survive generation.

Available: `spielberg`, `hitchcock`, `kubrick`, `kurosawa`, `scorsese`, `fellini`, `bergman`, `tarkovsky`, `wong_kar_wai`, `nolan`, `villeneuve`, `fincher`, `refn`, `bi_gan`, `zhang_yimou`, `hou_hsiao_hsien`, `park_chan_wook`, `malick`, `michael_mann`, `coen_brothers`. Index and how to add more: `director_styles/README.md`. Choosing between candidates, or explaining how two lenses differ: `director_styles/example_comparisons.md`, which directs one shared control scene through every lens.

**If the named director has no module, do not silently substitute one.** Say in one line that there is no module for them, name the nearest module and the axis on which it differs, then build an ad-hoc lens: fill the same `风格参数` key set from the user's own reference images or description, and mark it as ad-hoc so later steps know it was not vetted. Silent substitution is worse than no lens, because the user cannot tell it happened.

Precedence: **director lens > genre playbook > project tone > skill defaults.** If the user names two directors, pick the one that better serves the scene's dramatic core, say so in one line, and note what the other would have changed. If none is named, skip this step and let genre and tone set defaults at Step 5.

Style modules describe high-level methods. Never copy specific shots, lines, characters, or plots from real films.

### 5. Director's book / visual treatment

The reusable rule set that stabilizes every later prompt: tone and genre, lens and framing policy, camera grammar and the allowed move set, lighting logic and key direction, palette and color script, production design and era lock, performance register, editing rhythm and target ASL, sound direction, and the **invariant clauses** — the identity strings and lighting invariant that get pasted verbatim into every prompt.

Template: `../assets/director-book-template.md`. Depth: `lighting-and-color.md`, `genre-playbooks.md`, and `continuity-bible.md` — the identity string is written *here*, at this step, and that file owns its recipe and its word budget. Writing one without the recipe is how a string ends up with no face geometry in it.

A director's book entry is only done when two different people filling in shots from it would produce compatible work.

### 6. Blocking and staging

For every shot with people: start position, movement, interaction with space and props, camera relationship, end position, eyeline. Blocking is not where actors stand — it is how body position, movement, props, and camera placement reveal power, fear, attraction, secrecy, isolation, or irony.

Depth: `blocking-and-staging.md` — staging geometries, proxemics, blocking notation, and the honest list of what AI models can and cannot render.

### 7. Shot list and coverage

Build rows only after beats and blocking are clear. Each shot: number, duration, scene/location, story function, shot size, lens, angle, camera movement, blocking as start → motion → end, light direction and atmosphere, continuity anchors, transition, risk, production method and repair note.

Template: `../assets/shot-plan-template.md`. Grammar: `cinematic-language.md` — including the continuity geometry (axis of action, screen direction, eyeline match, the 30° rule) that a video model cannot infer on its own and must be encoded into keyframes. Risk values are read off the difficulty rubric in `production-workflow.md`; do not invent a second scale.

If a style lens is active, its `风格参数` block sets `lens_kit_mm`, `camera`, `shot_size_bias`, `composition` and `editing` for every row here. Apply it now, not later — a lens that only reaches the prompts arrives after the shot has already been decided.

#### 不同镜头用不同的生产方法

在分镜阶段按[成片元素与控制分工](element-control-contract.md)为各元素选择依据和实际控制，将方法、所需素材、控制目标与剩余不确定性写入 `Gen note`。一个镜头可以组合角色参考、空间布局、动作设计及后期，但每项有明确职责。首尾帧提供起止画面条件，不保证中间变形、特效方向或受力；具体路线按当前工具实际能力选择。真实游戏UI、奖励数值和转化信息仍用已核验素材及必要后期，缺少的素材标为缺口。

### 8. Keyframe strategy

Use the input mode selected at intake and its continuity risks. For outfit transitions, the linked planning skill owns the material selection; use this step only for any actual keyframe gap. For other tasks, choose among:

- **Single first frame** — simple action inside one stable composition.
- **First + last frame** — controlled transformation, a definite action endpoint, or a designed transition between two compositions.
- **Existing subject/appearance references** — when the mode accepts these and the existing assets plus action plan are sufficient; no new keyframe is needed solely to restate identity or costume.
- **Per-shot keyframes** — where a concrete composition, location or blocking anchor is needed and the selected mode can use it.
- **Storyboard panels** — when the model treats stills as slides. Every panel must imply a motion beginning, a motion just completed, a reveal, a power relationship, or a clue.

Template: `../assets/keyframe-prompt-template.md`. Consistency techniques (identity strings, character sheets, location plates, reference binding, building last frames from first frames): `image-model-adapters.md`.

If a style lens is active, this is the step where it is actually fixed. Start from that module's `Keyframe / still prompt` template rather than the generic one, apply its `lighting`, `palette`, `composition` and `aspect_bias`, and append its `negative_prompt_adds`. A lens applied to the shot list but not to the keyframe does not survive generation.

Gate: do not generate video from a keyframe that has not passed the pre-generation checks in `../assets/qc-checklist.md`.

### 9. Tool adapter selection

Apply Steps 8–10 to the AI-generated parts of the selected production method; carry recording, voice and AE tasks into the sound or assembly plan as needed.

Confirm the control surface selected at intake before writing the execution prompt. Read `ai-video-tool-adapters.md` (video) or `image-model-adapters.md` (stills). For an unfamiliar tool, inspect its available documentation or controls, then ask only for unresolved facts that change the plan. Route by actual capabilities: text-to-video, first/last-frame slots, subject/appearance references, camera controls, native audio, duration, multi-shot support, seed and video-to-video. A capability not yet checked stays conditional rather than creating a speculative image requirement.

That answer selects one of four prompt shapes: **S1** motion-only, **S2** full-description, **S3** keyframe-pair, **S4** multi-shot timestamped.

Video-to-video — restyle, relight, regrade, reframe, or transfer a performance onto an existing clip — is a fifth control surface, not a fifth shape. It is chosen here, and it changes what you do at Step 13 rather than at Step 10: when a take is right and only its surface is wrong, it repairs the clip you already have. Details: `ai-video-tool-adapters.md`.

### 10. AI video prompt construction

**S1 — Seedance motion-only** (image-to-video anchored to a concrete first frame). The approved frame carries identity, composition, lighting, setting, costume, and style. Subject/appearance references alone do not provide that complete frame; their missing scene and camera decisions still need explicit controls or text. The text defines motion, camera, timing, end state, and constraints — in this order:

```text
[Camera behavior]. [Subject starts in visible state], then [one primary action with pace and direction].
[Environment reacts subtly]. End with [clear final pose/composition].
Maintain [identity / costume / location / light direction]. Avoid [failure modes matching this shot's risk].
```

**S2 — full description** (text-to-video). The text carries everything:

```text
[Format/style]. [Subject with concrete visual identity]. [Location + era + time + atmosphere].
[Primary action]. [Shot size + lens + angle + camera movement]. [Light source + direction + quality].
[Composition]. [Audio if supported]. [Constraints].
```

**S3 — keyframe pair** (first frame + last frame). Describe the bridge between two approved stills, not the stills themselves:

```text
Start from the first image and end on the second. Between them, [one continuous transformation].
Camera [path, or explicitly locked]. Motion [eases in / holds a constant rate / accelerates once].
Preserve [declared identity and spatial invariants]. Implement [approved outfit / light / state changes] from their designated references.
Avoid [failure modes matching this shot's risk].
```

**S4 — multi-shot timestamped**:

```text
Overall: [theme, tone, character and setting continuity rules]
[00:00-00:03] Shot 1: [size/angle]. [action]. Camera [move]. [light or sound cue]
[00:03-00:06] Shot 2: [size/angle]. [action]. Camera [move]. [light or sound cue]
```

Per-segment lines carry action, camera, and at most one light or sound cue. Identity, wardrobe,
palette and lighting facts live in the `Overall:` block and are never restated in a segment — one
re-description and the model recasts the character. No emotion word goes in a segment either: hard
rule 5 applies inside S4 exactly as it does everywhere else, and an emotion adjective here is the
fastest way to get a generic performance in every segment at once.

Templates: `../assets/video-prompt-template.md`. Word-level craft, verb banks, the replacement table, negative-prompt library by failure class, and EN↔中文 terms: `prompt-lexicon.md`.

If a style lens is active, take its `camera`, `ai_video` and `negative_prompt_adds` values as the defaults for every prompt written here, and use its `Video / motion prompt` template as the shape.

### 11. Sound and dialogue plan

Sound is a directing decision, and in AI film it is the cheapest continuity glue available — one continuous ambience bed under a sequence hides an enormous amount of visual drift.

Plan five layers per shot: room tone, ambience, foley, spot effects, score. For dialogue, label each speaker, add turn-taking and reaction time, and verify the selected Seedance channel’s audio controls. Separate speaker clips, voice-over or off-screen lines are repair options when needed, not a universal split rule. Template: `../assets/sound-plan-template.md`. Depth: `sound-and-dialogue.md`.

### 12. Edit and assembly plan

Generated clips are raw material, not a cut. Specify the timeline: clip order, in/out points, trim handles, transition into each clip, and the audio layers running underneath. Design match cuts by building shot A's last frame and shot B's first frame together. Fix what can be fixed with a cutaway, a trim, or a dissolve rather than another generation.

Template: `../assets/edit-timeline-template.md`. Depth: `editing-and-assembly.md`.

### 13. QC and repair loop

Gate with `../assets/qc-checklist.md` when scoring a clip or a batch. When something fails, diagnose in this order — each bucket with the codes it usually resolves to:

1. **Asset mismatch** — references too inconsistent to hold identity (F1, F3, F16).
2. **Prompt overload** — over motion budget: too many actions or camera moves (F4, F6).
3. **Weak action** — the frame is a pose, not an implied motion (F2).
4. **Missing endpoint** — the prompt never says where the action ends (F5).
5. **Bad camera logic** — the move contradicts the framing or the space (F6).
6. **Continuity gap** — shot A's end state does not match shot B's start state (F7).
7. **Tool mismatch** — asking a model for a feature it does not control (F6, F11).

If the user reports more than one symptom, collect **every** code before proposing anything. Multiple codes usually share one root decision, and fixing them one at a time re-spends the same generation.

Apply retries only within current authorization. Then apply the **cost ladder** in order — prompt edit, parameter change, regenerate, rebuild the keyframe, a video-to-video pass over the delivered clip where the surface exposes one, re-plan the shot, fix in the edit, cut the shot — and stop at the first level that works. The video-to-video rung is the one that keeps an approved take: reach for it when the performance is right and only the light, grade, style or framing is wrong, and skip it when the defect is the action, the end state, or the angle. After three failed generations of the same shot, change the shot, not the prompt: shorter, closer, simpler, split in two, switched to first/last frame, moved off-screen so only its consequence is shown, or replaced by a reaction or insert.

Never run a diagnostic questionnaire. Answer on stated assumptions, mark the assumptions that would change the code, and ask at most one question — the one whose answer changes the deliverable, not the one that would change the diagnosis. Full coded diagnosis (F1–F19), root causes, and before/after repairs: `failure-modes.md`.

Repair output format:

```markdown
## Diagnosis
- [failure code and the specific mechanism, not a generic guess; one line per code if several]
- [shared root: the one decision that produced them all]

## Fix
- [the cheapest change on the cost ladder that addresses the root]

## Revised prompt
[clean prompt]

## Why this should work
[one or two sentences tied to the mechanism]
```

If no prompt, keyframe, or clip was supplied, do not invent the user's shot to fill the third section. Output the diagnosis, the fix ladder, and the prompt *shape* to rewrite into, then ask for the original prompt and which input mode produced it.

## Output modes

| Mode | Name | Use when | Template |
|---|---|---|---|
| A | Director Analysis | Interpretation, subtext, direction rules | inline (below) |
| B | Beat Sheet | Structure before shots | `../assets/beat-sheet-template.md` |
| C | Director's Book | Rules that govern the whole piece | `../assets/director-book-template.md` |
| D | Shot Plan | Shot list, storyboard plan, shooting table | `../assets/shot-plan-template.md` |
| E | Keyframe Prompt Pack | Stills, first/last frames, panels, character sheets | `../assets/keyframe-prompt-template.md` |
| F | Video Motion Prompt Pack | Assets exist, motion prompts needed | `../assets/video-prompt-template.md` |
| G | Continuity Bible | Recurring characters, locations, multi-scene work | `continuity-bible.md` |
| H | Sound & Dialogue Plan | Sound design, music, dialogue, VO | `../assets/sound-plan-template.md` |
| I | Edit & Assembly Plan | Cutting generated clips into a sequence | `../assets/edit-timeline-template.md` |
| J | QC & Repair | Something failed or looks wrong | `../assets/qc-checklist.md` |

Mode A shape:

```markdown
# Director Analysis

## Dramatic core
[one paragraph]

## Subtext
[one paragraph]

## Emotional arc
[opening → escalation → turn → closing]

## Visual thesis
[one concrete, photographable rule]

## Direction rules
- Camera:
- Lens:
- Lighting:
- Palette:
- Performance:
- Editing:
- Sound:
```

## Gotchas

- More cinematic adjectives is not better direction. Cut every word that does not change a decision.
- Beautiful shots that do not advance the story are the most expensive thing in the plan.
- Do not write "camera rotates, zooms, pans, tracks, and shakes" unless the tool controls that combination and the story needs it.
- Given reference images, do not reinvent costume, face, era, or location — describe them and lock them.
- "Looks like a slideshow" is not fixed by adding "cinematic motion." Add a specific subject action, an environmental reaction, and a motivated camera behavior with an end state.
- Horror and suspense want controlled stillness, negative space, delayed revelation, and sound — not constant camera movement.
- Comedy wants a wider frame, a longer hold, and a flat register. Do not direct a joke like a tragedy.
- Vertical is not cropped horizontal. Stage in depth, scale the subject up, and rethink every wide shot.
- Literary or satirical material keeps its idea. Do not convert every scene into genre spectacle.
- If the user reports a failure, diagnose the mechanism before rewriting. A rewrite that does not name the cause is a guess.

## Minimal working example

Request: "I have a keyframe of a man kneeling in a rainy old street. Make it into an AI video prompt."

Good:

```text
Low-angle medium close shot, locked camera with a very slow push-in, no other movement. The man starts
on one knee in the muddy rain-soaked street, one hand pressed flat against the wet ground. He breathes
heavily, then slowly lifts his head just far enough for his wet hair to fall aside and reveal one tired
eye. Rain keeps breaking the surface of the puddles around his robe; distant lightning briefly lifts the
far end of the empty street. End with him half-raised and still unsteady, weight on the forward knee,
head up. Maintain the same face, wet hair, crimson robe, stormy old Chinese street, low-key practical
lighting from a single lantern camera-left. No text, no watermark, no extra people, no plastic, no
rubber soles, no wristwatch, no printed logos.
```

Bad:

```text
Cinematic dark horror atmosphere, the man struggles in the rain and remembers his past, dramatic camera,
emotional, high quality, masterpiece.
```

The good version names a camera behavior and forbids the rest, gives one primary action with visible body mechanics, adds one environmental reaction, states an end state, repeats the invariants, and lists only the negatives this shot actually risks — as nameable instances, not as the category "modern objects," which a model cannot resolve. The bad version names a mood and hopes.

## Self-check before responding

- Does every shot have a story function you could state in one clause?
- Is there exactly one dominant camera move per shot — or a deliberate none?
- Does every action have a start state and an end state?
- Are the invariants written verbatim, identically, in every prompt of the scene?
- Do adjacent shots clear the cut geometry — two size steps on an unchanged axis, or one step plus a
  30°+ angle change — unless the match is deliberate? Rungs and the rule: `cinematic-language.md`.
- Are the negatives limited to this shot's real risks?
- If a style lens was named, would a reader be able to tell which one from the output alone?
- Does the output stay clear of any specific shot, line, character, or plot beat from a real film?
- Is the output proportional to what was asked?
