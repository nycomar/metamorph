# Workflows

API-format ComfyUI workflow JSONs. These are shipped artifacts, not build output:
the app loads them, overrides node inputs by id, and submits them to Comfy Cloud.

- `stage.json` — one stage image, SDXL base + depth ControlNet + IPAdapter (img2img)
- `stage_flux.json` — one stage image, FLUX.1-dev + depth ControlNet (img2img, no IPAdapter)
- `evolve.json` — one LTX-2.5 pass with the stage images pinned to frames as guides

The pipeline selects the stage graph with `image_model` / `--image-model` / the
`IMAGE_MODEL` env var: `sdxl` (`stage.json`, default) or `flux` (`stage_flux.json`).

FLUX was benchmarked on the ring source but did not beat SDXL for this job (it
lost the solid wreath silhouette and read as tiny sprouts, not wet moss), so the
runtime default stays `sdxl`. The FLUX graph remains available with
`--image-model flux`.

## FLUX stage graph (`stage_flux.json`, `image_model=flux`)

FLUX.1-dev is guidance-distilled: it runs at **cfg 1.0** and uses `FluxGuidance`
instead of classifier-free guidance. There is no negative prompt in the working
sense — node `5` is an empty encode that only exists because
`ControlNetApplyAdvanced` requires a negative socket. There is no IPAdapter; the
depth ControlNet carries the silhouette.

| Input | Node id | Field | Value |
| --- | --- | --- | --- |
| Source photo | `1` | `image` | uploaded source filename |
| Source size | `17` | `width`, `height`, `crop` | 768, 768, `center` |
| UNet | `2` | `unet_name`, `weight_dtype` | `flux1-dev.safetensors`, `default` |
| Text encoders | `3` | `clip_name1`, `clip_name2`, `type` | `t5xxl_fp8_e4m3fn_scaled.safetensors`, `clip_l.safetensors`, `flux` |
| Positive prompt | `4` | `text` | per-stage prompt |
| Empty negative | `5` | `text` | `""` (unused at cfg 1.0) |
| Depth map | `6` | `image` | `17` (DepthAnythingV2 preprocessor) |
| ControlNet | `7` | `control_net_name` | `Flux1Dev_CNup-FP8.safetensors` |
| Union mode | `18` | `type` | `depth` (Shakker Labs union selector) |
| FLUX guidance | `8` | `guidance` | 3.5 |
| Depth ControlNet | `9` | `strength`, `vae` | 0.65, `11[0]` |
| Sampling shift | `10` | `model`, `max_shift`, `base_shift`, `width`, `height` | `2`, 1.15, 0.5, 768, 768 |
| VAE | `11` | `vae_name` | `ae.safetensors` |
| img2img init | `13` | `pixels`, `vae` | `17`, `11` |
| KSampler | `14` | `seed` | 1337 |
| KSampler | `14` | `steps`, `cfg`, `sampler_name`, `scheduler`, `denoise` | 20, 1.0, `euler`, `simple`, 1.0 |
| Sampler inputs | `14` | `model`, `positive`, `negative`, `latent_image` | `10[0]`, `9[0]`, `9[1]`, `13[0]` |
| Decode | `15` | `samples`, `vae` | `14[0]`, `11[0]` |
| Save | `16` | `filename_prefix` | `metamorph/stage_{i}` |

`9` applies the depth ControlNet after `FluxGuidance`; its positive/negative
outputs feed the sampler directly (`14.positive = ["9", 0]`,
`14.negative = ["9", 1]`). The `VAEEncode` init is only there to satisfy the
sampler — `denoise` is 1.0, so generation starts from noise.

## SDXL stage graph (`stage.json`, `image_model=sdxl`)

The winning recipe is depth-only structure with a light IPAdapter style anchor.
Concrete, visible material nouns in the prompt steer SDXL; naming the source noun
or saying "the same ring becomes X" does not.

| Input | Node id | Field | Value |
| --- | --- | --- | --- |
| Source photo | `1` | `image` | uploaded source filename |
| Source size | `17` | `width`, `height`, `crop` | 768, 768, `center` |
| Checkpoint | `2` | `ckpt_name` | `sd_xl_base_1.0.safetensors` |
| Positive prompt | `3` | `text` | per-stage prompt |
| Negative prompt | `4` | `text` | fixed quality negatives |
| Depth map | `6` | `image` | `17` (DepthAnythingV2 preprocessor) |
| ControlNet | `7` | `control_net_name` | `controlnet-depth-sdxl-1.0.safetensors` |
| Depth ControlNet | `9` | `strength` | 0.55 |
| IPAdapter apply | `12` | `weight`, `weight_type` | 0.25, `linear` |
| img2img init | `13` | `pixels`, `vae` | `17`, `2[2]` |
| KSampler | `14` | `seed` | 1337 |
| KSampler | `14` | `steps`, `cfg`, `sampler_name`, `scheduler`, `denoise` | 28, 6.0, `dpmpp_2m`, `karras`, 1.0 |
| Sampler inputs | `14` | `model`, `positive`, `negative`, `latent_image` | `12[0]`, `9[0]`, `9[1]`, `13[0]` |
| Decode | `15` | `samples`, `vae` | `14[0]`, `2[2]` |
| Save | `16` | `filename_prefix` | `metamorph/stage_{i}` |

The canny loader/preprocessor/apply nodes are gone from this graph (former ids
`5`, `8`, `10`). Do not pass a canny override: there is no node `10` any more.
IPAdapter is SDXL-only; `--ipa-weight` / `--ipa-weight-type` are rejected when
`image_model=flux`.
