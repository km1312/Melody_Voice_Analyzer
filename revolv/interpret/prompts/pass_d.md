# version: p1.0.0
PASS D: WRITE UP.

Write the final output from the Pass A facts and the clusters that survived Pass C. Add no reading that Pass C did not pass.

notes
- summary: three to five plain sentences on what happened and what was decided. If the reader gave a goal, open with where the call left that goal.
- decisions, action_items (owner, task, due), open_questions, key_numbers: one terse line each, with turn ids. Write them the way the reader's own notes would read. No filler such as 'the participants discussed'.
speakers
- For each main speaker other than the reader: up to three things they seemed to care about, each with the reason in words (raised it first, returned to it three times, asked four questions about it) and turn ids. Set nothing_notable where that is the honest answer.
insights
- One per surviving cluster. claim: the reviewer's sentence. evidence: the supporting observations as turn id, exact quote, kind, moment ids and a short description. alternatives: the ordinary explanations, kept. follow_up: one specific question the reader could ask this person next time that would confirm or rule out the reading.
so_what
- Up to three next steps for the reader, each tied to an insight id or a fact.

Shape:
{"topics":[{"id":"tp1","label":"","spans":[["T001","T014"]],"raised_by":""}],
 "notes":{"summary":"","decisions":[{"text":"","turn_ids":[]}],
          "action_items":[{"owner":"","task":"","due":"","turn_ids":[]}],
          "open_questions":[{"text":"","turn_ids":[]}],
          "key_numbers":[{"text":"","turn_ids":[]}]},
 "speakers":[{"label":"SPEAKER_02","nothing_notable":false,
              "cares_about":[{"topic_id":"tp3","why":"","turn_ids":[]}]}],
 "insights":[{"id":"ins_001","layer":"unsaid","speaker":"SPEAKER_02","topic_id":"tp3",
              "claim":"","likelihood":"","evidence_confidence":"",
              "evidence":[{"turn_id":"","quote":"","channel":"","moment_ids":[],"description":""}],
              "alternatives":[""],"follow_up":""}],
 "so_what":[{"text":"","refs":["ins_001"]}]}

<pass_a_facts>
{{PASS_A_FACTS_AND_TOPICS_JSON}}
</pass_a_facts>

<kept>
{{PASS_C_KEPT_WITH_OBSERVATIONS_JSON}}
</kept>
