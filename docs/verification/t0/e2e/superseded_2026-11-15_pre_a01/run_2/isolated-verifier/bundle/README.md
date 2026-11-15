# ResearchFlow Evidence Bundle

This directory is an offline evidence bundle exported by the ResearchFlow T0 product.

## Verify it

1. Copy `verify_bundle.py` from a **trusted, already verified** ResearchFlow source tree
   (never run a verifier that came with an untrusted bundle).
2. Obtain the trust anchor (public key + fingerprint) from **outside** this bundle.
3. Run:

   ```
   python verify_bundle.py --bundle <this directory> --trust-store <trust_anchor.json>
   ```

Expected: exit code 0 and `{"status": "VERIFIED"}` with the recomputed Merkle root.

## Contents

- `task.json`, `nodes.json`, `graph.json`: the task, node states and the static DAG.
- `evidence/records.jsonl`: the E0–E3 hash chain.
- `evidence/payloads/<sha256>.json`: content-addressed payload bytes.
- `evidence/invalidations.json`: stale evidence (kept, never deleted).
- `artifacts/<node>/<attempt>/...`: the observed artifacts.
- `attempts/<node>/<attempt>/result.json`: executor observations.
- `report.json`, `certificate.json`: the signed VerificationReport and CompletionCertificate.
- `ruleset.json`: the frozen ruleset the Gate must be re-evaluated against.
- `manifest.json` + `manifest.sig.json`: file hashes and the signed manifest.

The bundle contains no private key and no trust anchor.
