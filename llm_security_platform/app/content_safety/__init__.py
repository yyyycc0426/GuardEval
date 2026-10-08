"""Content-safety evaluation track.

A parallel evaluation pipeline that calibrates the platform's classifiers and
judges against public, human-labeled safety benchmarks (currently HateXplain
hate-speech / offensive-language / normal classification).

This track is intentionally separate from the attack/defense (ASR) pipeline:
its task is *content classification* against ground-truth labels, not red-team
attack-success measurement. It reports accuracy / macro-F1 / confusion matrix,
not ASR.
"""
