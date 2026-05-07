---
title: "OmniVoice is surprisingly good"
date: 2026-05-07T20:00:00
type: post
tags: [til, tts, voice-cloning, audio, machine-learning]
subtitle: "cloned my voice in ~30 seconds on an M4 Pro"
description: "Tried OmniVoice, a zero-shot voice cloning TTS model. Cloned my voice in Turkish and English, ran tongue twisters, and was impressed by the results."
---

I tried [OmniVoice](https://github.com/k2-fsa/OmniVoice) this afternoon because I saw [a post on r/LocalLLaMA](https://www.reddit.com/r/LocalLLaMA/comments/1t4rst5/i_know_this_isnt_technically_an_llm_but_omnivoice/) and got curious. It's a zero-shot voice cloning TTS model that claims 600+ languages. I recorded two short voice memos on my phone, one in Turkish and one in English, dropped them into the web UI, and 30 seconds later voila I had cloned versions of my voice saying things I never said. Each sample took one or two tries to get right.

## Setup

Clone the repo and sync dependencies with uv:

```bash
git clone https://github.com/k2-fsa/OmniVoice.git
cd OmniVoice
uv sync
```

Then launch the demo:

```bash
omnivoice-demo --ip 0.0.0.0 --port 8001
```

A Gradio web UI opens up. You upload a reference audio, type its transcript, type whatever you want the clone to say, and hit generate. No training, no configuration, no API keys.

## Voice cloning

I recorded two short samples of myself and used them as references.

<input type="checkbox" id="lang-toggle" class="lang-toggle-input">
<label for="lang-toggle" class="lang-btn">Show Turkish</label>

<div class="audio-section">
  <h3>Original voice</h3>
  <div class="audio-row">
    <div class="audio-item lang-tr">
      <div class="audio-text">"Selam ben Cemrehan bu da benim ses kaydım"</div>
      <audio controls>
        <source src="/static/audio/cemrehan-tr.mp3" type="audio/mpeg">
      </audio>
    </div>
    <div class="audio-item lang-en">
      <div class="audio-text">"Hello my name is Cemrehan and this is my voice record"</div>
      <audio controls>
        <source src="/static/audio/cemrehan-en.mp3" type="audio/mpeg">
      </audio>
    </div>
  </div>

  <h3>Cloned voice</h3>
  <div class="audio-row">
    <div class="audio-item lang-tr">
      <div class="audio-text">"Selam bu ses gerçek değil klonlandı ama neredeyse aynı"</div>
      <audio controls>
        <source src="/static/audio/cloned-tr.mp3" type="audio/mpeg">
      </audio>
    </div>
    <div class="audio-item lang-en">
      <div class="audio-text">"Hi this isn't real its cloned but it is almost the same"</div>
      <audio controls>
        <source src="/static/audio/cloned-en.mp3" type="audio/mpeg">
      </audio>
    </div>
  </div>
</div>

The timbre is close. Not perfect, you can hear a synthetic texture on some consonants, but if I played this for someone who doesn't know me well, they might not notice. For zero training and ~30 seconds of inference, that's kind of wild.

## Tongue twisters

I also wanted to see how it handles actually hard speech. Turkish *tekerleme* (tongue twisters) are genuinely difficult, the kind of thing that ties your mouth in knots. If the model can do these without falling apart, it's doing something real.

<div class="audio-section">
  <div class="audio-row">
    <div class="audio-item lang-tr">
      <div class="audio-text">"Çarşıda koza ucuz, çarşıda darı ucuz, çarşıda boza da ucuz mu?"</div>
      <audio controls>
        <source src="/static/audio/twiter-tr.mp3" type="audio/mpeg">
      </audio>
    </div>
    <div class="audio-item lang-en">
      <div class="audio-text">"She sells seashells by the seashore"</div>
      <audio controls>
        <source src="/static/audio/twister-en.mp3" type="audio/mpeg">
      </audio>
    </div>
  </div>
</div>

It nails tongue twisters too. When I tried to record them myself I failed a couple of times. The model didn't.

## What I actually care about

Voice cloning has been around. Usually you need minutes of clean audio, a training run, and patience. This needs 3–10 seconds of reference audio and about 30 seconds on an M4 Pro. No cloud API, no queue, no configuration. I ran `uv sync` and clicked a button.

The quality ceiling is probably higher with cleaner audio. These were casual phone recordings. But even with what I had, the results are good enough to be interesting.

Most voice cloning tools treat non-English as an afterthought. This doesn't. I tried it on Turkish mostly to clone my friends' voices and mess with them. They were all surprised.
