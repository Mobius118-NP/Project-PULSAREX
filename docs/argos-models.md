# Locally installed ARGOS models

Installed on 18 November 2026 in `%USERPROFILE%\ARGOS\models`:

| File | Purpose | SHA-256 |
|---|---|---|
| `face_detection_yunet_2023mar.onnx` | Existing YuNet face detection | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |
| `w600k_r50.onnx` | ArcFace recognition embeddings | `4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43` |

ArcFace was downloaded from the official InsightFace
[v0.7 buffalo_l archive](https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip).
The downloaded archive SHA-256 was
`80ffe37d8a5940d59a7384c201a2a38d4741f2f3c51eef46ebb28218a7b0ca2f`.
Only `w600k_r50.onnx` was extracted, to the exact configured model path. It is
174,383,860 bytes. ONNX Runtime loaded it using the CPU provider and returned a
finite `(1, 512)` result from zero-valued `(1, 3, 112, 112)` input. This checks model
loading/inference, not recognition accuracy. The application does not need network
access to use the installed model.

**License:** InsightFace's pretrained models are for **non-commercial research
only**, separately from its MIT-licensed library source. See the publisher's
[license statement](https://github.com/deepinsight/insightface/tree/master/python-package#license).
YuNet provenance is [OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet).
Model files remain in ARGOS's git-ignored `models` directory; they are not added to
the PULSAR repository or existing executable releases.

No identities were automatically created. An empty catalogue is valid: in the
ARGOS menu, start the camera with face IDs enabled, select the visible track and
explicitly enroll the consenting participant. Templates are written only by an
explicit catalogue action and remain in ARGOS's local data folder.
