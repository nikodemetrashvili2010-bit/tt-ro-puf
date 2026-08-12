# The run notes, and what they are not evidence of

Six files in this folder are the working notes I wrote while running the
simulations behind Sections 5 and 6 of the paper. Five places in this repository
cite them as proof that a prediction was written down before the run it
predicts. Until 2026-08-11 they were not in the repository at all, so that
citation pointed at a file no reader could open, which is a bad way to make a
methodological argument.

| Note | The run it covers |
|---|---|
| [`macro_rc_run_steps.md`](macro_rc_run_steps.md) | the Arm B macro distributed-RC comparison, item 7 |
| [`instance_run_steps.md`](instance_run_steps.md) | the sixteen per-instance Arm B extractions, item 8 |
| [`armb_corner_run_steps.md`](armb_corner_run_steps.md) | Arm B at the ss and ff corners, item D |
| [`mux_run_steps.md`](mux_run_steps.md) | the selection-path check, item 2 |
| [`boundary_run_steps.md`](boundary_run_steps.md) | the boundary-through-selector sweep |
| [`supply_run_steps.md`](supply_run_steps.md) | the supply sweep and the slow-corner rerun |

## The honest part

**Nothing here proves when these files were written.** They were kept as local
notes on my own disk and none of them was committed until 2026-08-11, so git
cannot date them, and a file that first appears in history today is a file that
could have been written today. If you want to treat the whole pre-registration
claim as unproven, the evidence supports you and I would rather say so than
imply a guarantee the repository cannot give.

What I can offer instead is weaker but checkable: **the predictions in these
notes are sometimes wrong, and the notes say so.** `macro_rc_run_steps.md` names
a band of 0.85 to 0.97 percent for the distributed-lumped shift and calls the
prediction 564.3 MHz. The run came back at 566.05 MHz, a shift of 0.801 percent,
which is outside the band it named. `instance_run_steps.md` records pointing
`PDK_ROOT` at the ciel tree instead of the volare one and the deck generator
stopping with a missing-file error. A prediction file written after the fact
tends to be right every time, and these are not.

Read them that way. They are a record of how the work went, offered so the
method can be argued with, not a timestamp I am asking anyone to trust.

## Two things left as they were

The commands are quoted with the absolute paths I actually typed, on a machine
where this repository sits at `/mnt/d/silicon/silicon chip` and the PDK at
`/home/pc/pdks`. Substitute your own. I have not rewritten them into portable
form, for the same reason the build outputs in `macro/romacro_final/` are left
exactly as the flow wrote them: editing a record of a run makes it a worse
record. `REPRODUCIBILITY.md` is the file that gives these runs as portable
commands, and that is the one to follow if you want to repeat them.

Several notes end by running `backup_to_repo.sh`. That script and its test
harness live on my disk and are not mirrored here; `LICENSING.md` says why and
`REPRODUCIBILITY.md` describes what they do.

## Two notes that stayed local

`release_steps.md` and `rc_rerun_steps.md` are not here. Neither is cited as
evidence for anything, and both are housekeeping, how to cut a release and how
to rerun a job I had already run, rather than a record of a prediction.
