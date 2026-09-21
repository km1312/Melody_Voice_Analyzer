# version: p1.0.0
PASS B: COMPETING READINGS.

Below are the topics, facts and observations from Pass A, then the analysis view for reference. Work speaker by speaker, topic by topic. Skip the reader if they are identified.

Where observations of at least two different kinds cluster for one speaker on one topic, write two or three competing readings of what was going on for that speaker. One of them must be an ordinary explanation: thinking time, word-finding, a bad connection, multitasking, a second language, reading from a screen, or a mislabelled speaker. For each reading, list the observation ids that support it and those that cut against it. Then say which reading the evidence favours, how likely it is, and how good the evidence is. If the readings are balanced, say roughly even chance.

Use these layers, and skip any the evidence does not reach:
- stance_commitment: how firm this speaker's agreement or commitment really was. Compare the words of the commitment with how it was delivered and what followed it.
- unsaid: a reservation, objection or question that may not have been voiced. Look for a slow reply, a preface such as 'well' or 'yeah, no', an account or excuse, weak agreement followed by a change of subject, or a question that was answered with something else.
- relational: who led and who deferred on this topic, one-sided floor-taking, a shift in rapport, laughter that was or was not shared.

Where observations do not cluster, write nothing. Put speakers with nothing notable in nothing_notable. A short list of well-evidenced clusters is better than a long one.

Shape:
{"clusters":[{"id":"cl1","speaker":"SPEAKER_02","topic_id":"tp3","layer":"unsaid",
   "readings":[{"id":"r1","text":"","ordinary":false,"supports":["ob12","ob13"],"against":["ob20"]},
               {"id":"r2","text":"","ordinary":true,"supports":["ob13"],"against":[]}],
   "favoured":"r1","likelihood":"roughly even chance","evidence_confidence":"low","why":""}],
 "nothing_notable":["SPEAKER_01"]}

<pass_a>
{{PASS_A_JSON}}
</pass_a>

<analysis_view>
{{NUMBERED_VIEW}}
</analysis_view>
