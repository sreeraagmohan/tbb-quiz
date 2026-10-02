You are checking practice questions written for UPSC Prelims aspirants from one news story. You get the story and the questions without their answer keys. The story is the only source of truth: judge each question by what the story says, not by your own knowledge of events, which may be outdated.

For each question, in order:

1. Solve it using only the story. `chosen` is the index of the option the story supports (0 = a, 1 = b, 2 = c, 3 = d).
2. `exactly_one_correct`: true only if exactly one option is defensibly correct given the story. In statement and pairs questions, each statement or pair must be clearly true or clearly false from the story; one the story doesn't address makes this false.
3. `grounded_in_story`: true only if every fact needed to answer is in the story.
4. `problem`: name any defect in a short phrase (for example: ambiguous wording, needs outside knowledge, not anchored in time, two defensible options, trivial, tests an opinion, stem contains an error). Use an empty string if there is none.
5. `verdict`: "keep" if it is a fair, unambiguous Prelims-style question an aspirant could learn from; otherwise "drop".

Return one result per question, in the order given.
