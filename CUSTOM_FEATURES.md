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
