# Expense assistant repository instructions

Read MODEL_HANDOFF.txt, SPECIFICATION.txt, IMPLEMENTATION_CONTRACT.json, policy_sources/rule_registry.json, policy_sources/reference_data.json and docs/REQUIREMENTS.json before changing this project.

Implementation of milestones M0–M8 is authorized (stage IMPLEMENTATION_M0_M8, see docs/DECISIONS.json). Work one milestone at a time in backlog order and stop at milestone boundaries or unavailable external dependencies. A later explicit user instruction to implement a milestone authorizes that milestone; update docs/DECISIONS.json and continue within that scope without repeatedly asking for approval.

Use the supplied fixed hosted small-model API. Resolve every number and enumeration from the rule registry and reference data rather than hard-coding them. Keep money calculations and domain rules in plain Python; isolate LangChain and LangGraph in adapters and workflows. Never add booking/payment tools or substitute a larger/local model. Keep all test answer keys outside RAG and model inputs.

Preserve stable test IDs. Do not change expected answers to make failing code pass; document a genuine policy/test defect and its correction in docs/CHANGELOG.txt. Cite requirement and golden IDs in changes. Run python build_package.py when you change a source of a derived artifact, then python validate_package.py for documentation/data edits and the relevant implementation tests once they exist. Report what actually ran.

Never commit secrets, private receipts, runtime databases, raw traces or .env. Dependency pins are proposed until a tested lockfile is committed. Follow docs/REPOSITORY_WORKFLOW.txt and respect the user's explicit instructions over repository guidance.
