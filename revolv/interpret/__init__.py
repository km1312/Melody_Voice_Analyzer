"""The interpretation layer: stage 10.

Reads what the pipeline wrote (segments and the analysis report), builds the
numbered model view and the prompt pack, verifies whatever a model returns,
and writes `.insights.json` and `.notes.md`. Nothing in this package touches
audio models, the GPU, or the network beyond a loopback provider.
"""
