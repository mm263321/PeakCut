# Custom PeakCut features

This branch (\`custom-features\`) contains requested additions on top of the official PeakCut \`main\` branch.

## Branch policy

- Keep official upstream updates on \`main\`.
- Develop custom features only on \`custom-features\`.
- Before future custom work, merge the latest official \`main\` into this branch and resolve any shared-file conflicts deliberately.
- Never force-push \`main\`.
- Never commit \`.env\`, API keys, browser cookies, videos, recordings or personal data.

## Phase 1: custom layout editor

The first custom feature adds an editor to an individual clip's **Layout → Custom layout editor** option.

1. Preview the clip's original source in its original aspect ratio.
2. Select a facecam crop and a gameplay crop separately.
3. Move or resize the source crop rectangles.
4. Arrange the two selected regions on a 9:16 canvas using facecam-top, facecam-bottom, facecam-overlay or side-by-side presets.
5. Move or resize each output frame and preview the result.
6. Press **Save and re-make clip** to apply the layout to the actual MP4.

Implementation is kept mostly modular:

- \`studio/custom_layout.py\`: normalized rectangle validation and FFmpeg filter graph.
- \`web/custom-layout.js\`: editor interface, pointer controls and preview.
- \`studio/render.py\`, \`studio/jobs.py\`, \`studio/server.py\`: small integration points for rendering, re-making and authenticated source preview.
- \`tests/test_custom_layout.py\`: invalid-input tests and a real FFmpeg render test.

This first phase edits an individual existing clip. It does not yet add custom layouts to Home → Options or automatically apply creator-specific layouts to newly generated live clips. Those are later phases. The official live detection, recording, YouTube session, Twitch and Kick code is left unchanged.

## Future upgrade workflow

1. Synchronize the fork's \`main\` branch with the original PeakCut repository.
2. Merge \`main\` into \`custom-features\`.
3. Resolve shared-file changes without dropping custom modules.
4. Run \`python tests/run.py\` and manually test the custom editor, live recording and exports.
5. Push changes only to \`custom-features\` until verified.

## Phase 2: native 1080p / 2K / 4K exports

The source-download ceiling and final export size are separate settings.

- Home → Options → Maximum source download: 720p, 1080p or the highest available up to 2160p (4K).
- Home → Options → Export resolution: 1080p (1080×1920), 2K-class (1440×2560) or 4K (2160×3840).
- Home → Options → Video encoder: H.264, HEVC/H.265 or AV1.
- Home → Options → Export quality: Balanced, High quality or Maximum quality.
- Individual clip editor → Export settings: each clip can override the job's export resolution, encoder and quality when re-rendering.

studio/export_settings.py validates the choices, detects FFmpeg encoders and tries NVIDIA NVENC first when listed. If a hardware encoder is listed but fails at runtime, it tries another encoder for the same selected codec. It does not silently change HEVC or AV1 into H.264.

studio/render.py builds the composition and caption coordinates at the selected output dimensions. A lower-resolution source can be upscaled to the requested output dimensions, but upscaling cannot restore detail that is not present in the source.

Existing single MP4 downloads, bulk ZIP downloads, clip history and the 1080p export default remain supported. The default source-download ceiling is now 2160p; uploaded files are not re-downloaded or altered before clipping.

Test: tests/test_export_settings.py checks settings validation, codec fallback order, quality profiles and real 1080p/2K/4K MP4 renders.
