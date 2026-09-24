# Afterword: UX acceptance

The product helps a family organize records, distinguish evidence from unknowns, prepare questions and track follow-up. HP informs the visual design and intended deployment platform; hardware promotion does not belong in these daily tasks.

## Core journeys

| Task | Expected outcome | Failure to prevent |
| --- | --- | --- |
| Find a record | Search/type filters lead to a readable original excerpt. | Losing the query after inspecting evidence. |
| Review a finding | Understand what is known, what is unknown and which record supports each statement. | Treating a read acknowledgement as legal verification. |
| Compare sources | Switch sources without losing reading position or working notes. | Scrolling back to the page top after every selection. |
| Prepare a letter | Edit, reload safely, preview, export and return to the related action. | Losing a draft or implying a downloaded letter was sent. |
| Track follow-up | Save a reminder/note and move the action to waiting or completed. | Silent invalid dates or accidental completion without recovery. |
| Recover a mistake | Undo status, favorite or queue changes using the visible control or Ctrl/Command+Z outside text fields. | Invisible, untappable or prematurely dismissed Undo. |
| Understand privacy | Identify what is stored, what has been shared and how to export/reset. | Mistaking local browser storage for encryption or live device processing. |

## Implemented safeguards

- Notes and letters autosave after a short pause, on navigation and on page exit. A failed write is labelled session-only.
- Invalid reminder input does not replace the prior stored reminder with an apparently successful save.
- Same-page source selection preserves scroll and keyboard focus. Page changes focus the main content.
- Undo remains available for 20 seconds, pauses dismissal while focused/hovered and leaves the focus order when hidden.
- File errors name the problem while retaining accepted selections. Queue removal never changes the original file.
- No unsolicited modal tour, hardware advertisement, fake inference animation, generated landscape or unmeasured performance counter.
- Sample data and disconnected services are labelled where they affect a decision. No analytics or feedback collection is installed.

## What the current checks establish

Browser checks establish interaction behavior and responsive layout for the tested cases. They do not establish satisfaction, legal correctness, security of a production archive, accessibility certification or capacity for 100,000 users. Backend parsing, inference, authorization and encrypted storage remain separate engineering work.

Verified cases include autosave recovery on immediate reload without pressing Save, clickable Undo restoring action count, separate saved templates, note retention, reset undo, file validation and persistence, and source switching at the same measured scroll position with focus transferred to the chosen source.

## How to evaluate the satisfaction target

1. Begin with consenting participants using fictional case material. Recruit across technical familiarity, age, device and assistive-technology needs; avoid requiring disclosure of a personal bereavement.
2. Ask participants to complete the journeys above without coaching. Record completion, critical errors, assistance required, recovery success and a post-task ease rating. Collect written reasons for low scores.
3. Investigate repeated confusion before expanding the pilot. Re-test changed journeys with new participants, including keyboard and screen-reader users.
4. In a real pilot, gather an optional overall rating after meaningful use. Report the invitation count, response count, response rate, sample characteristics and full rating distribution alongside the mean. Do not claim a 100,000-user score from a small or selectively solicited sample.
5. Treat 4.9/5 as an aspiration. Predefine how satisfaction is calculated and validate it with actual data; do not fabricate reviews, selectively suppress criticism or substitute interface polish for measured usefulness.

## Design references

- [Nielsen Norman Group: progressive disclosure](https://www.nngroup.com/articles/progressive-disclosure/) — keep optional technical explanation out of the main task.
- [Recognition rather than recall](https://www.nngroup.com/articles/recognition-and-recall/) — keep sources and the originating action available beside a draft.
- [Error-message guidance](https://www.nngroup.com/articles/error-message-guidelines/) — explain the problem and the recovery step.
- [W3C status messages](https://www.w3.org/WAI/WCAG21/Understanding/status-messages) — announce saves/errors without stealing focus.
- [W3C enhanced target sizing](https://www.w3.org/WAI/WCAG22/Understanding/target-size-enhanced.html) — aim for comfortable controls; this is not a claim of full conformance.

## Ambient background acceptance

- Artwork is decorative and absent from the accessibility tree. Its motion preference is available in Appearance settings.
- Motion is limited to Overview and Memories; document, letter and evidence surfaces remain still.
- The Still preference preserves the scene and survives reload. It is available in Appearance preferences. Device reduced motion takes priority, including preference changes while the app is open.
- Animation pauses offscreen, behind a dialog and in a hidden tab. Printing and forced-colors modes omit it.
- Time-of-day tones use only the device clock; no location request or added network resource is needed.
