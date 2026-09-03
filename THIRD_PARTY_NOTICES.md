# Third-party components

This repository does not redistribute language models, video models, ComfyUI, LM Studio, or custom-node packages.

The optional runtime integrations are:

- LM Studio OpenAI-compatible local API: <https://lmstudio.ai/docs/developer/openai-compat>
- ComfyUI: <https://github.com/Comfy-Org/ComfyUI>
- FastVideo FastH3 preview weights: <https://huggingface.co/FastVideo/FastVideo-FastH3-4-step-Preview-v1-VSA-DataFree>

The accelerated workflow optionally expects a compatible custom node exposing `SolAttnMiniMax`. Its implementation is not bundled. Set `FASTH3_USE_SOL_ATTN=0` to build the graph without that optional node.

Review the current license and usage terms at each upstream source before downloading or redistributing any external component or model.
