# Execution Plan: JingXu.Workbench Completion and Stabilization

## Overview
This plan completes and stabilizes the JingXu.Workbench offline Windows video workbench by first repairing the broken WPF presentation test harness, then committing the accumulated implementation work in recoverable slices, and finally finishing the remaining milestones in dependency order. The approach prioritizes robustness, clean architecture boundaries, deterministic test behavior, and production readiness over short-term workarounds.

## Goals
1. Eliminate the single blocking presentation-layer failure pattern so all ViewModel and presentation tests become reliable.
2. Commit the large uncommitted implementation backlog in coherent milestone-aligned slices with green build/test gates.
3. Complete the remaining M2/M3/M4 implementation and verification work after the baseline is stabilized.
4. Preserve offline-first behavior, clean-architecture separation, immutable job snapshots, atomic persistence, deterministic seeding, and Chinese user-facing error surfaces.

## Architecture / Approach
- Keep Domain free of WPF, filesystem, and process references.
- Keep Application responsible for orchestration and abstractions only.
- Keep Infrastructure responsible for FFmpeg/FFprobe/Whisper/Tesseract/process/persistence concerns.
- Keep Presentation responsible for MVVM, observable state, commands, and UI behaviors only.
- Fix presentation test reliability through injectable dispatcher abstraction, not test hacks.
- Use gates after every major phase: `dotnet build` must be clean, `dotnet test` must be green, and changes must be committed before proceeding.
- Use milestone order from the implementation plan: stabilize first, then commit, then M2 e2e, then M4 completion.

## Execution Steps

### Phase 1: Diagnose and repair presentation test failures

#### Step 1.1: Verify current solution baseline
**Objective**: Confirm the solution still builds cleanly, quantify current failure distribution, and verify whether the existing `RunOnUi` fallback is masking dispatcher behavior.
**Details**:
- Run `dotnet build JingXu.Workbench.sln -c Debug` in `.worktrees/jingxu-implementation/`.
- Run `dotnet test JingXu.Workbench.sln -c Debug`.
- Record per-project pass/fail counts for Domain.Tests, Application.Tests, Infrastructure.Tests, Presentation.Tests, and IntegrationTests.
- Inspect the first Presentation failure stack traces and confirm the shared root cause is `Dispatcher.Invoke` inside ViewModel `RunOnUi` helpers.
- Inspect the existing `RunOnUi` null/fallback behavior to verify whether tests pass because real dispatcher invocation is being bypassed; document whether failures are present, masked, or environment-dependent.
- Identify the expected failing M4 integration test(s) by name so later gates can reference them explicitly.
**Inputs**: Existing worktree code, current tests.
**Outputs**: Baseline build/test summary, confirmed root-cause hypothesis, and named expected integration failure.
**Quality Criteria**: The problem must be clearly mapped to presentation-layer dispatcher behavior, not domain logic.

#### Step 1.2: Extract injectable dispatcher abstraction
**Objective**: Replace direct `Application.Current.Dispatcher` usage in ViewModels with a testable abstraction.
**Details**:
- Create `src/JingXu.Workbench.Application/Abstractions/IUiDispatcher.cs` with `void Invoke(Action action); T Invoke<T>(Func<T> func); bool CheckAccess();`.
- Create `src/JingXu.Workbench/Bootstrap/WpfUiDispatcher.cs` implementing `IUiDispatcher` and falling back to direct invocation when `Application.Current` is null or when `CheckAccess()` returns true; use `DispatcherPriority.DataBind`.
- Create `tests/JingXu.Workbench.Presentation.Tests/Infrastructure/DirectUiDispatcher.cs` implementing `IUiDispatcher` synchronously with `CheckAccess()` returning true.
- Update `AppCompositionRoot` to accept an optional `IUiDispatcher?` (default `new WpfUiDispatcher()`) and propagate it into `CompositionViewModel`, `OverlayEditorViewModel`, and `GateMonitorViewModel` constructors.
- Verify constructor signatures, factory methods, and test factories all propagate the dispatcher explicitly.
**Inputs**: Existing ViewModels, composition root, test factories.
**Outputs**: New abstraction files and wiring changes.
**Quality Criteria**: Abstraction must be minimal, explicit, and consistent with existing bootstrap patterns.

#### Step 1.3: Refactor affected ViewModels to remove private dispatcher helpers
**Objective**: Eliminate the duplicated `RunOnUi` anti-pattern from presentation-layer code.
**Details**:
- Modify `src/JingXu.Workbench/Features/Composition/CompositionViewModel.cs` to accept the dispatcher abstraction and remove private `RunOnUi`.
- Modify `src/JingXu.Workbench/Features/Overlays/OverlayEditorViewModel.cs` to accept the dispatcher abstraction and remove both private `RunOnUi` overloads.
- Modify `src/JingXu.Workbench/Features/Shell/GateMonitorViewModel.cs` to accept the dispatcher abstraction and remove private `RunOnUi`.
- If `RenderQueueViewModel` also contains a private dispatcher helper, apply the same refactor for consistency.
- Ensure genuine cross-thread callbacks use the injected dispatcher, while async `[RelayCommand]` methods use direct property assignment after await.
**Inputs**: ViewModel source files, dispatcher abstraction.
**Outputs**: Cleaner ViewModels with explicit threading dependencies.
**Quality Criteria**: No ViewModel may reference `Application.Current` directly. Async command paths must avoid nested dispatcher blocking patterns.

#### Step 1.3b: Verify dispatcher references are removed from ViewModels
**Objective**: Ensure no ViewModel directly references `Application.Current` after the refactor.
**Details**:
- Run `rg "Application\.Current" src/JingXu.Workbench/Features/` and confirm the expected result is zero matches outside infrastructure/converter code.
- If any ViewModel still references `Application.Current`, remove the direct usage and route it through the injected dispatcher abstraction.
- Confirm `dotnet build` remains clean after the verification.

#### Step 1.4: Repair presentation test factories and async test wiring
**Objective**: Align tests with the refactored ViewModels and remove deadlock-prone synchronous blocking.
**Details**:
- Update `tests/JingXu.Workbench.Presentation.Tests/Composition/CompositionViewModelTestFactory.cs` to inject `DirectUiDispatcher` and add `static async Task<CompositionViewModel> LoadedCompositionAsync(...)`.
- Update `tests/JingXu.Workbench.Presentation.Tests/Shell/ShellViewModelTestFactory.cs` to inject `DirectUiDispatcher`.
- Update `tests/JingXu.Workbench.Presentation.Tests/Overlays/OverlayEditorViewModelTests.cs` and related factories to inject `DirectUiDispatcher` consistently; rename any duplicate fake probe names if ambiguity exists.
- Update `tests/JingXu.Workbench.Presentation.Tests/Shell/GateMonitorViewModelTests.cs` as required by constructor signature changes.
- Convert the composition tests that depend on async import/setup to proper `async Task` tests using `await LoadedCompositionAsync(...)` where needed.
- Confirm no test still expects the old private `RunOnUi` signature or behavior.
**Inputs**: Refactored ViewModels, test factories, failing tests.
**Outputs**: Updated test factories and passing presentation tests.
**Quality Criteria**: `dotnet test tests/JingXu.Workbench.Presentation.Tests` must pass with zero dispatcher-related failures.

#### Step 1.5: Re-run full test suite and lock stabilization
**Objective**: Confirm the presentation fix does not regress other layers and establishes a clean baseline.
**Details**:
- Run `dotnet test JingXu.Workbench.sln -c Debug` again.
- Confirm Domain, Application, and Infrastructure remain green.
- Confirm Presentation becomes green.
- Confirm the single expected IntegrationTests M4-gate failure remains isolated and understood.
- If new warnings or failures appear, fix them immediately before proceeding.
**Inputs**: Refactored code and updated tests.
**Outputs**: Full solution test summary.
**Quality Criteria**: The repository must be in a clean green state for milestone-committable code, except the accepted future-gate integration test.

### Phase 2: Commit the accumulated implementation in coherent slices

#### Commit rollback rule
**Objective**: Keep repository history clean if any commit slice breaks the required gates.
**Details**:
- Before each slice, review `git status` and verify no unintended files are staged.
- If a slice fails `dotnet build` or `dotnet test`, fix the code in-place, re-run the gates, and amend the commit before proceeding.
- Do not proceed to the next slice with a broken commit in history.
- If a slice must be abandoned, revert it explicitly and re-evaluate dependency order before continuing.

#### Step 2.1: Commit Tasks 4–5
**Objective**: Establish persistence, runtime resolution, and safe process execution baseline.
**Details**:
- Begin with `git status --short` and verify no unexpected staged or stashed changes exist.
- Stage Domain/Rendering, Application/Abstractions, Application/Projects, Infrastructure/Persistence, Infrastructure/Processes, Infrastructure/Runtime, Infrastructure/Rendering progress parser, and related tests/lock files.
- Run `dotnet build` and `dotnet test` before commit.
- Commit message: `feat: persist projects and render queue atomically` / `feat: run media sidecars safely` as planned, or a single combined slice if history is cleaner that way.
**Inputs**: Related source/test files.
**Outputs**: Committed baseline for persistence and process safety.
**Quality Criteria**: Build/test must remain green after commit.

#### Step 2.2: Commit Tasks 6–7
**Objective**: Commit media probing and render coordination.
**Details**:
- Stage Infrastructure/Media, Application/Rendering, queue tests, probe tests, and related factories.
- Verify queue recovery, bounded concurrency, and failure isolation behaviors remain intact.
- Commit message: `feat: probe imported media metadata` and `feat: coordinate persistent render jobs`.
**Inputs**: Probe/coordinator/test files.
**Outputs**: Committed baseline for import and queue scheduling.
**Quality Criteria**: No regressions in queue state machine or probe behavior.

#### Step 2.3: Commit Task 8
**Objective**: Commit WPF shell, themes, and navigation.
**Details**:
- Stage Bootstrap, Themes, ShellWindow, Features/Shell, presentation tests, and assets.
- Verify theme contract tests, layout tests, and navigation tests remain green.
- Commit message: `feat: build professional WPF workbench shell`.
**Inputs**: Presentation shell files.
**Outputs**: Committed presentation shell baseline.
**Quality Criteria**: Presentation tests remain green after commit.

#### Step 2.4: Commit Tasks 9–12
**Objective**: Commit render profile, FFmpeg command compilation, overlays, effects, and render execution/finalization.
**Details**:
- Stage Domain/Rendering, Domain/Overlays, Domain/Effects, Application/Composition, Application/Overlays, Infrastructure/Rendering, and all related tests.
- Verify render decision, quality preset mapping, command compilation, overlay timeline, and executor validation logic remain green.
- Commit message: `feat: compile core ffmpeg render commands` through `feat: execute and finalize safe video renders`.
**Inputs**: Render/overlay/effect implementation and tests.
**Outputs**: Committed M2 core rendering pipeline.
**Quality Criteria**: No regressions in overlay timing, effect determinism, or temp/atomic output logic.

#### Step 2.5: Commit Task 13
**Objective**: Commit the composition workbench workflow and remaining presentation features.
**Details**:
- Stage remaining Features (Composition, Overlays, Queue, Settings, Subtitles) and Presentation tests.
- Verify import, preview, enqueue, overlay editing, and queue view behaviors remain stable.
- Commit message: `feat: complete batch composition workbench`.
**Inputs**: Remaining Presentation features.
**Outputs**: Committed end-to-end UI workflow.
**Quality Criteria**: Presentation tests remain green after commit.

#### Step 2.6: Commit Tasks 15–18
**Objective**: Commit subtitle domain/application/infrastructure work.
**Details**:
- Stage Domain/Subtitles, Application/Subtitles, Infrastructure/Subtitles, subtitle rendering filters, subtitle tests, and related factories.
- Verify SRT/ASS codec, timeline validation, removal/burn-in filters, and workflow tests remain green.
- Commit message: `feat: complete offline subtitle laboratory`.
**Inputs**: Subtitle subsystem files.
**Outputs**: Committed subtitle pipeline.
**Quality Criteria**: Subtitle-related tests remain green.

#### Step 2.7: Commit docs/scripts and stabilization artifacts
**Objective**: Commit supporting docs, scripts, and non-code artifacts required by later milestones.
**Details**:
- Stage README, THIRD_PARTY_NOTICES, docs/, scripts/, runtime readme, manifest-related assets, and lock files.
- Keep release-only artifacts without staged binaries out of source control unless explicitly required.
- Commit message: `docs: add architecture, testing, and release documentation`.
**Inputs**: Documentation and script files.
**Outputs**: Committed support material for M4.
**Quality Criteria**: Repository remains buildable and testable.

### Phase 3: Verify M2 integration end-to-end

#### Step 3.1: Run composition/overlay/audio integration tests
**Objective**: Confirm real FFmpeg-based M2 behavior after stabilization and commits.
**Details**:
- Run `dotnet test tests/JingXu.Workbench.IntegrationTests --filter "CompositionRenderTests|OverlayRenderTests|AudioAndCoverTests"` in `.worktrees/jingxu-implementation/`.
- If FFmpeg/FFprobe are not available, verify the tests skip cleanly with meaningful messages.
- If failures occur, trace them to the narrowest lower-level regression test before fixing implementation code.
**Inputs**: Integration tests, local runtime binaries.
**Outputs**: M2 integration verification result.
**Quality Criteria**: All required M2 integration tests must pass or cleanly skip due to runtime unavailability; no fake green status.

#### Step 3.2: Fix any exposed pipeline defects
**Objective**: Correct command compilation, executor, overlay, or validation issues surfaced by integration tests.
**Details**:
- For each failure, add a lower-level regression test first.
- Fix only the narrow code path responsible for the defect.
- Re-run the targeted tests and then the broader suite.
**Inputs**: Integration failures, lower-level tests.
**Outputs**: Corrected implementation and regression coverage.
**Quality Criteria**: No tolerance loosening without codec/runtime justification documented in code/docs.

### Phase 4: Complete remaining M4 work

#### Step 4.1: Implement Task 19 settings/runtime manifest/diagnostics
**Objective**: Provide runtime manifest validation, settings diagnostics, and first-run checks.
**Details**:
- Implement or correct `src/JingXu.Workbench.Infrastructure/Runtime/RuntimeManifest.cs`, `src/JingXu.Workbench.Infrastructure/Runtime/RuntimeManifestValidator.cs`, `src/JingXu.Workbench/Features/Settings/SettingsViewModel.cs`, `src/JingXu.Workbench/Features/Settings/SettingsView.xaml`, `src/JingXu.Workbench/Bootstrap/SelfTestRunner.cs`, and `build/runtime-manifest.json`.
- Wire diagnostics into the settings experience with actionable Chinese messages.
- Add/update tests for manifest validation and runtime diagnostics.
- Verify gate commands: `dotnet test tests/JingXu.Workbench.Infrastructure.Tests --filter RuntimeManifestValidatorTests` and `dotnet test tests/JingXu.Workbench.Presentation.Tests --filter SettingsViewModelTests`.
**Inputs**: Existing Infrastructure runtime code, settings UI.
**Outputs**: Working runtime diagnostics and settings workflow.
**Quality Criteria**: Tests pass; missing runtime components are reported with Chinese guidance and suggested actions.

#### Step 4.2: Implement Task 20 runtime staging/licensing/docs
**Objective**: Ensure offline runtime staging, licensing notices, and documentation are complete.
**Details**:
- Implement/fix `scripts/Resolve-Runtimes.ps1`, `runtime/README.md`, `README.md`, `THIRD_PARTY_NOTICES.md`, and docs under `docs/`.
- Ensure manifest-to-artifact verification logic exists and is testable.
- Add packaging/runtime tests for hash/notice/source-offer expectations.
- Verify gate command: `dotnet test tests/JingXu.Workbench.IntegrationTests --filter RuntimePackageTests`.
**Inputs**: Manifest, docs, scripts.
**Outputs**: Release-support material and runtime staging verification.
**Quality Criteria**: Runtime package and notice tests must pass for M4.

#### Step 4.3: Implement Task 21 portable build and installer artifacts
**Objective**: Produce portable and installer release artifacts according to the plan.
**Details**:
- Implement/fix `scripts/Build-Portable.ps1`, `scripts/Build-Installer.ps1`, and WiX sources.
- Keep user project/output directories outside installer-managed scope.
- Add/update artifact structure and installer scope tests.
- Verify tooling prerequisites before packaging tests, including WiX availability; if WiX is missing, ensure tests fail with explicit Chinese guidance rather than vague errors.
- Verify gate commands: `dotnet test tests/JingXu.Workbench.IntegrationTests --filter PortableArtifactTests` and `dotnet test tests/JingXu.Workbench.IntegrationTests --filter WixSourceTests`.
**Inputs**: Build scripts, WiX sources, staged runtime.
**Outputs**: Portable and installer packaging.
**Quality Criteria**: Portable/installer tests pass; installer never manages user project/output directories.

#### Step 4.4: Implement Task 22 final acceptance
**Objective**: Execute final acceptance verification and document results.
**Details**:
- Implement/fix `scripts/Verify-Release.ps1` and `docs/acceptance-report.md`.
- Run clean build, test, format, packaging, and release verification flows.
- Record spec-to-test/manual evidence mapping for sections 5–14.
- Verify final gate commands include clean restore/build/test/format/release verification per the implementation plan.
**Inputs**: All prior deliverables.
**Outputs**: Acceptance report and verified release state.
**Quality Criteria**: No required verification row may remain unresolved.

## Integration Points
- Application abstractions must remain the contract boundary between Presentation and Infrastructure.
- Composition, overlays, subtitles, and queue flows all depend on consistent ViewModel-to-orchestrator wiring.
- Subtitle removal/burn-in must integrate with render execution in the correct order.
- Runtime manifest/staging/docs/scripts must align with packaging and acceptance verification.

## Quality Assurance
- `dotnet build JingXu.Workbench.sln -c Debug` must succeed with 0 warnings/errors after each phase gate.
- `dotnet test JingXu.Workbench.sln -c Debug` must remain green after each committable slice.
- Production code must avoid direct `Application.Current` access in ViewModels and avoid shell string concatenation for external processes.
- Tests must assert on observable behavior, remain deterministic, and use async patterns correctly.
- Final release verification must not rely on skipped required tests or placeholder artifacts.

## Risk Register
- **Dispatcher refactor drift**: New ViewModels could reintroduce direct dispatcher usage. Mitigate by keeping the abstraction mandatory and adding review-time checks.
- **Large commit regression**: Accumulated changes may hide regressions. Mitigate by committing in milestone slices with build/test gates.
- **Runtime environment variance**: FFmpeg/Tesseract/Whisper availability affects tests. Mitigate with clear skip messages and release gates that prohibit required-test skipping.
- **Packaging environment mismatch**: Missing WiX/runtime staging could break M4. Mitigate by prechecking tool availability and gating artifact tests.
- **Test timing flakiness**: Async UI and queue tests can be sensitive. Mitigate with deterministic waits, event-driven checks, or appropriately increased timeouts.

## File Structure
After execution, the worktree should retain the existing clean-architecture layout and contain completed implementations under:

- `src/JingXu.Workbench.Domain/`
- `src/JingXu.Workbench.Application/`
- `src/JingXu.Workbench.Infrastructure/`
- `src/JingXu.Workbench/`
- `tests/`
- `scripts/`
- `docs/`
- `build/`
- `runtime/README.md`
- `README.md`
- `THIRD_PARTY_NOTICES.md`
