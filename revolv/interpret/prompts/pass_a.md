# version: p1.0.0
PASS A: OBSERVE. Do not interpret yet.

Read the analysis view below and return JSON in the shape shown.

1. topics: the 4 to 10 topics the conversation covered, in order. For each: a short label, the turn ids where it starts and ends (a topic may have several spans), and who raised it first.
2. facts: decisions made, action items (owner, task, due date if one was said), questions left unanswered, and key numbers or names. Cite turn ids for each. Use only what was said.
3. observations: things a careful listener would note, each tied to one turn. For each: the turn id, the speaker, an exact quote of 25 words or fewer, the kind (lexical, timing, prosody, disfluency, interaction), a one-line neutral description, any moment ids involved, and the topic id. Describe; do not explain. 'Replies after a long gap, far above their usual' is an observation. 'Reluctant' is not.
   Look for, at least: hedges and boosters; firm against soft commitment language; answers that do not address the question; abrupt topic changes and who made them; topics a speaker raised unprompted or came back to; questions asked; long gaps before replies relative to that speaker's median; pauses inside turns; clusters of mid-sentence fillers, restarts and cut-offs; someone taking the floor against simple backchannels; laughter; turns with a strong note or several notes at once.
   Skip isolated weak notes. Aim for 20 to 60 observations on a half-hour call.
4. per_speaker: for each main speaker, the topic ids they spent the most words on, raised first, returned to, and asked about.

Shape:
{"topics":[{"id":"tp1","label":"","spans":[["T001","T014"]],"raised_by":"SPEAKER_00"}],
 "facts":{"decisions":[{"text":"","turn_ids":[]}],
          "action_items":[{"owner":"","task":"","due":"","turn_ids":[]}],
          "open_questions":[{"text":"","turn_ids":[]}],
          "key_numbers":[{"text":"","turn_ids":[]}]},
 "observations":[{"id":"ob1","turn_id":"T057","speaker":"SPEAKER_02","quote":"",
                  "channel":"lexical","description":"","moment_ids":[],"topic_id":"tp3"}],
 "per_speaker":[{"speaker":"SPEAKER_02","most_words_on":[],"raised_first":[],
                 "returned_to":[],"asked_about":[]}]}

<analysis_view>
{{NUMBERED_VIEW}}
</analysis_view>
