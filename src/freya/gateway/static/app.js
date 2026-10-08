"use strict";

// Everything Freya sends is shown with textContent, never as HTML: her
// replies and tool results are not trusted markup.

const $ = (id) => document.getElementById(id);

const messages = $("messages");
const gallery = $("gallery");
const banner = $("banner");
const imageWorking = $("image-working");
const consoleOutput = $("console-output");

const CONSOLE_LINE_LIMIT = 1000;
const CONSOLE_SHOWN_KEY = "freya.consoleShown";

let socket = null;
let retryDelay = 500;
let currentReply = null;
let status = {};
let consoleLines = [];
let replaying = false;

const WHO = {
  window: "You",
  typed: "You (console)",
  voice: "You (voice)",
};

// -- helpers ---------------------------------------------------------

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function nearBottom(box) {
  return box.scrollHeight - box.scrollTop - box.clientHeight < 80;
}

function addToChat(node) {
  const stick = nearBottom(messages);
  $("chat-empty").hidden = true;
  messages.appendChild(node);
  if (stick) messages.scrollTop = messages.scrollHeight;
}

function addMessage(kind, who, text) {
  const bubble = element("div", "message " + kind);
  bubble.appendChild(element("span", "who", who));
  const body = element("span", "body", text);
  bubble.appendChild(body);
  addToChat(bubble);
  return { bubble, body };
}

function send(message) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(message));
    return true;
  }
  return false;
}

function when(seconds) {
  return new Date(seconds * 1000).toLocaleString([], {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function remember(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch (error) {
    // Storage can be unavailable; the tab then just starts hidden.
  }
}

function recall(key) {
  try {
    return localStorage.getItem(key);
  } catch (error) {
    return null;
  }
}

// -- conversation ------------------------------------------------------

function finishReply() {
  if (currentReply) {
    currentReply.bubble.classList.remove("is-writing");
    if (!currentReply.body.textContent.trim()) currentReply.bubble.remove();
    currentReply = null;
  }
}

function showEvent(event) {
  switch (event.type) {
    case "user":
      finishReply();
      addMessage("from-user", WHO[event.source] || "You", event.text);
      break;

    case "assistant_start":
      finishReply();
      currentReply = addMessage("from-freya is-writing", "Freya", "");
      break;

    case "assistant_chunk": {
      if (!currentReply) {
        currentReply = addMessage("from-freya is-writing", "Freya", "");
      }
      const stick = nearBottom(messages);
      currentReply.body.textContent += event.text;
      if (stick) messages.scrollTop = messages.scrollHeight;
      break;
    }

    case "assistant_end":
      finishReply();
      break;

    case "notice":
      finishReply();
      addToChat(element("p", "notice", event.text));
      break;

    case "image_started":
      imageWorking.textContent = "Generating: " + event.prompt;
      imageWorking.hidden = false;
      break;

    case "image_ready":
      finishReply();
      addChatImage(event.image);
      // When an earlier conversation is being replayed, the gallery is
      // filled from its own list instead.
      if (!replaying) {
        imageWorking.hidden = true;
        addImage(event.image, true);
        if (!$("view-images").classList.contains("is-active")) {
          $("images-badge").hidden = false;
        }
      }
      break;

    case "image_failed":
      imageWorking.hidden = true;
      break;

    case "console":
      addConsoleLines([event.text]);
      break;

    case "voice":
      voiceResult(event);
      break;

    case "status":
      showStatus(event.status);
      break;

    case "error":
      addToChat(element("p", "notice", event.text));
      break;
  }
}

// -- console ---------------------------------------------------------

function addConsoleLines(lines) {
  const stick = nearBottom(consoleOutput);
  consoleLines = consoleLines.concat(lines).slice(-CONSOLE_LINE_LIMIT);
  consoleOutput.textContent = consoleLines.join("\n");
  if (stick) consoleOutput.scrollTop = consoleOutput.scrollHeight;
}

function showConsoleTab(shown) {
  $("tab-console").hidden = !shown;
  remember(CONSOLE_SHOWN_KEY, shown ? "1" : null);
  if (shown) {
    showView("console");
    consoleOutput.scrollTop = consoleOutput.scrollHeight;
  } else if ($("view-console").classList.contains("is-active")) {
    showView("chat");
  }
}

function isCommand(text) {
  return text.startsWith("/") || text.startsWith("\\");
}

// "exit" or "quit" on its own, in any letter case, is the quit command,
// as it is in the terminal. A sentence that contains the word is not.
function isQuitWord(text) {
  const word = text.trim().toLowerCase();
  return word === "exit" || word === "quit";
}

// Typed text is a message for Freya unless it starts with a slash, in
// which case it is one of her commands. Opening the Console tab is the
// one command handled here in the window.
function submitText(text) {
  if (isQuitWord(text)) {
    return send({ type: "command", text: text.trim() });
  }

  if (!isCommand(text)) {
    return send({ type: "say", text });
  }

  const command = text.slice(1).trim().toLowerCase();

  if (command === "terminal" || command === "console") {
    showConsoleTab(true);
    return true;
  }

  return send({ type: "command", text });
}

// -- voice -----------------------------------------------------------
//
// The Voice tab is built from what each speech engine says it can do.
// A kind of voice work is only offered through engines that declare
// it, and a saved voice is only ever used with the engine that made it.

let voice = null;
let voiceRequests = 0;
let voicePending = null;

const KIND_NAMES = {
  preset: "Preset voice",
  blend: "Blend of supplied voices",
  clone: "Cloned from a recording",
  design: "Designed from a description",
};

const STATUS_NAMES = {
  ready: "Ready",
  not_installed: "Not installed",
  not_configured: "Not set up",
};

function engineById(id) {
  return ((voice && voice.engines) || []).find((engine) => engine.id === id);
}

function fillSelect(select, options, keep) {
  const previous = keep === undefined ? select.value : keep;
  select.replaceChildren();
  options.forEach((option) => {
    const item = element("option", "", option.label);
    item.value = option.value;
    item.disabled = Boolean(option.disabled);
    select.appendChild(item);
  });
  if (options.some((o) => o.value === previous && !o.disabled)) {
    select.value = previous;
  } else {
    const first = options.find((o) => !o.disabled);
    if (first) select.value = first.value;
  }
}

function voiceMessage(text, isError) {
  const line = $("voice-message");
  line.textContent = text;
  line.classList.toggle("is-error", Boolean(isError));
}

// `then` runs with the answer when the request succeeds.
function voiceSend(action, fields, working, then) {
  voiceRequests += 1;
  const request = "v" + voiceRequests;
  if (send({ type: "voice", action, request, ...fields })) {
    voicePending = { request, then };
    voiceMessage(working || "Working…");
  }
}

function voiceResult(event) {
  showVoice(event.state);

  // Another window's request only refreshes what is shown here.
  if (!voicePending || event.request !== voicePending.request) return;
  const then = voicePending.then;
  voicePending = null;

  if (event.error) {
    voiceMessage(event.error, true);
    return;
  }

  if (event.clip) {
    const player = $("voice-player");
    const source = "/audio/" + encodeURIComponent(event.clip.id);
    player.src = source;
    player.hidden = false;
    player.play().catch(() => {});
    const link = $("voice-download");
    link.href = source;
    link.hidden = false;
    voiceMessage(event.clip.seconds + " seconds of speech.");
  } else {
    voiceMessage("Done.");
  }

  if (then) then(event);
}

function languageOptions(engine) {
  return engine.controls.languages.map((language) => ({
    value: language.code,
    label: language.available
      ? language.name
      : language.name + " (needs extra language packages)",
    disabled: !language.available,
  }));
}

function voiceOptions(engine, code) {
  const language = engine.controls.languages.find((l) => l.code === code);
  return ((language && language.voices) || []).map((v) => ({
    value: v.id,
    label: v.label,
  }));
}

function engineRow(engine) {
  const row = element("li");
  const about = element("div", "about");
  about.appendChild(element("span", "name", engine.name));
  about.appendChild(element("span", "detail", engine.summary));
  if (engine.detail) about.appendChild(element("span", "detail", engine.detail));
  row.appendChild(about);
  if (!engine.local) row.appendChild(element("span", "state is-cloud", "Cloud service"));
  row.appendChild(
    element(
      "span",
      "state" + (engine.status === "ready" ? " is-ready" : ""),
      STATUS_NAMES[engine.status] || engine.status,
    ),
  );
  return row;
}

function fillEngineList(listId, ids) {
  const list = $(listId);
  list.replaceChildren();
  ids.map(engineById).filter(Boolean).forEach((engine) => {
    list.appendChild(engineRow(engine));
  });
  if (!list.children.length) {
    list.appendChild(element("li", "", "No engine offers this yet."));
  }
}

function presetEngine() {
  return ((voice && voice.sections.preset) || [])
    .map(engineById)
    .find((engine) => engine && engine.status === "ready");
}

function blendEngine() {
  return ((voice && voice.sections.blend) || [])
    .map(engineById)
    .find((engine) => engine && engine.status === "ready");
}

function refreshPresetVoices() {
  const engine = presetEngine();
  if (engine) {
    fillSelect($("preset-voice"), voiceOptions(engine, $("preset-language").value));
  }
}

function refreshBlendVoices() {
  const engine = blendEngine();
  if (!engine) return;
  const options = voiceOptions(engine, $("blend-language").value);
  fillSelect($("blend-a"), options);
  fillSelect($("blend-b"), options);
  if ($("blend-a").value === $("blend-b").value && options.length > 1) {
    $("blend-b").value = options[1].value;
  }
}

function refreshPlaygroundProfiles() {
  const profiles = ((voice && voice.profiles) || []).filter(
    (profile) => profile.engine === $("play-engine").value,
  );
  fillSelect(
    $("play-profile"),
    profiles.length
      ? profiles.map((p) => ({ value: p.id, label: p.name }))
      : [{ value: "", label: "No saved voices for this engine yet", disabled: true }],
  );
  $("play-speak").disabled = !profiles.length;
}

function profileRow(profile) {
  const engine = engineById(profile.engine);
  const row = element("li");
  const about = element("div", "about");
  about.appendChild(element("span", "name", profile.name));
  about.appendChild(
    element(
      "span",
      "detail",
      (KIND_NAMES[profile.kind] || profile.kind) +
        " · " +
        (engine ? engine.name : profile.engine) +
        " only",
    ),
  );
  row.appendChild(about);

  const isActive = voice.active_profile === profile.id;
  const use = element(
    "button",
    isActive ? "primary" : "ghost",
    isActive ? "Freya's voice" : "Use for Freya",
  );
  use.type = "button";
  use.disabled = !profile.can_be_freyas_voice;
  use.title = profile.can_be_freyas_voice
    ? isActive
      ? "Click to go back to her default voice."
      : "Make this the voice Freya speaks with."
    : "Freya speaks English with Kokoro, so only an English Kokoro voice can be hers.";
  use.addEventListener("click", () => {
    voiceSend("use", { profile: isActive ? null : profile.id }, "Changing Freya's voice…");
  });
  row.appendChild(use);

  const remove = element("button", "ghost", "Delete");
  remove.type = "button";
  remove.addEventListener("click", () => {
    voiceSend("delete", { profile: profile.id }, "Deleting…");
  });
  row.appendChild(remove);

  return row;
}

// -- cloning and designing ---------------------------------------------

// A recording is decoded here, in the page, and sent to Freya as plain
// mono samples, so she never has to parse an audio file she was given.
const RECORDING_RATE = 24000;
const RECORDING_CHUNK = 48 * 1024;
const CLONE_SLIDERS = ["temperature", "exaggeration", "cfg_weight"];
const SLOW_NOTE = " The first time takes longer while the engine loads.";

// The recording Freya already holds for the chosen file, and the voice
// that was last designed.
let cloneReference = null;
let designReference = null;

function readyEngines(section) {
  return ((voice && voice.sections[section]) || [])
    .map(engineById)
    .filter((engine) => engine && engine.status === "ready");
}

function engineOptions(engines) {
  return engines.map((engine) => ({ value: engine.id, label: engine.name }));
}

function cloneModel() {
  const engine = engineById($("clone-engine").value);
  const models = (engine && engine.controls.models) || [];
  return models.find((model) => model.id === $("clone-model").value) || models[0];
}

function refreshCloneControls() {
  const engine = engineById($("clone-engine").value);
  const model = cloneModel();
  if (!engine || !model) return;

  fillSelect(
    $("clone-language"),
    model.languages.map((l) => ({ value: l.code, label: l.name })),
  );

  CLONE_SLIDERS.forEach((name) => {
    const range = engine.controls[name];
    const shown = Boolean(range) && model.controls.includes(name);
    $("clone-" + name + "-field").hidden = !shown;
    if (!shown) return;

    const input = $("clone-" + name);
    input.min = range.min;
    input.max = range.max;
    input.step = range.step;
    if (!input.dataset.touched) input.value = range.default;
    $("clone-" + name + "-value").textContent = Number(input.value).toFixed(2);
  });

  const reference = engine.controls.reference || {};
  $("clone-transcript-field").hidden = !reference.transcript;
}

function refreshCloneModels() {
  const engine = engineById($("clone-engine").value);
  if (!engine) return;
  fillSelect(
    $("clone-model"),
    (engine.controls.models || []).map((m) => ({ value: m.id, label: m.name })),
  );
  refreshCloneControls();
}

function refreshDesignControls() {
  const engine = engineById($("design-engine").value);
  if (!engine) return;
  fillSelect(
    $("design-language"),
    (engine.controls.languages || []).map((l) => ({ value: l.code, label: l.name })),
  );
  fillSelect(
    $("design-model"),
    (engine.controls.models || []).map((m) => ({ value: m.id, label: m.name })),
  );
}

// The imported recording, decoded: { name, stamp, audio }.
let cloneClip = null;
let cloneListening = null;

function recordingLimits() {
  return (voice && voice.reference_seconds) || { min: 6, max: 30 };
}

function cloneStart() {
  return Number($("clone-start").value);
}

function describeCloneClip() {
  const limits = recordingLimits();
  const note = $("clone-file-note");

  if (!cloneClip) {
    note.textContent =
      "Choose an audio file or drop one here: " +
      limits.min + " to " + limits.max + " seconds of one person speaking.";
    return;
  }

  const length = cloneClip.audio.duration;
  const from = cloneStart();
  const to = Math.min(length, from + limits.max);
  $("clone-start-value").textContent = from.toFixed(1) + " s";
  note.textContent =
    cloneClip.name + " · " + length.toFixed(1) + " seconds long · using " +
    from.toFixed(1) + " to " + to.toFixed(1) + " s" +
    (length < limits.min ? " · too short to clone from" : "");
}

function stopListening() {
  if (cloneListening) {
    cloneListening.close();
    cloneListening = null;
  }
  $("clone-listen").textContent = "Play the part that will be used";
}

// Take in an audio file the owner chose or dropped. It is decoded
// here in the page; nothing is sent to Freya until Preview or Save.
async function importRecording(file) {
  if (!file) return;
  stopListening();
  $("clone-file-note").textContent = "Reading " + file.name + "…";

  const context = new AudioContext();
  try {
    const audio = await context.decodeAudioData(await file.arrayBuffer());
    cloneClip = {
      name: file.name,
      stamp: [file.name, file.size, file.lastModified].join("|"),
      audio,
    };
  } catch (error) {
    cloneClip = null;
    $("clone-listen").hidden = true;
    $("clone-start").disabled = true;
    $("clone-file-note").textContent =
      file.name + " could not be read as audio. Try a WAV, MP3, M4A, FLAC or OGG file.";
    return;
  } finally {
    context.close();
  }

  const slider = $("clone-start");
  const latest = Math.max(0, cloneClip.audio.duration - recordingLimits().min);
  slider.max = Math.floor(latest * 2) / 2;
  slider.value = 0;
  slider.disabled = Number(slider.max) === 0;
  $("clone-listen").hidden = false;
  describeCloneClip();
}

function listenToRecording() {
  if (cloneListening) {
    stopListening();
    return;
  }
  if (!cloneClip) return;

  const context = new AudioContext();
  const source = context.createBufferSource();
  source.buffer = cloneClip.audio;
  source.connect(context.destination);
  source.onended = stopListening;
  source.start(0, cloneStart(), recordingLimits().max);
  cloneListening = context;
  $("clone-listen").textContent = "Stop";
}

// The chosen part of the recording as mono 16-bit samples.
async function recordingSamples() {
  const from = cloneStart();
  const seconds = Math.min(cloneClip.audio.duration - from, recordingLimits().max);
  const frames = Math.max(Math.floor(seconds * RECORDING_RATE), 1);
  const offline = new OfflineAudioContext(1, frames, RECORDING_RATE);
  const source = offline.createBufferSource();
  source.buffer = cloneClip.audio;
  source.connect(offline.destination);
  source.start(0, from);
  const samples = (await offline.startRendering()).getChannelData(0);
  const pcm = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i += 1) {
    pcm[i] = Math.max(-1, Math.min(1, samples[i])) * 32767;
  }
  return pcm;
}

function wireImport() {
  const drop = $("clone-drop");
  const picker = $("clone-file");

  $("clone-import").addEventListener("click", () => picker.click());
  picker.addEventListener("change", () => {
    importRecording(picker.files[0]);
    // So that choosing the same file again is noticed.
    picker.value = "";
  });
  $("clone-listen").addEventListener("click", listenToRecording);
  $("clone-start").addEventListener("input", () => {
    stopListening();
    describeCloneClip();
  });

  ["dragenter", "dragover"].forEach((name) => {
    drop.addEventListener(name, (event) => {
      event.preventDefault();
      drop.classList.add("is-over");
    });
  });
  ["dragleave", "drop"].forEach((name) => {
    drop.addEventListener(name, (event) => {
      event.preventDefault();
      drop.classList.remove("is-over");
    });
  });
  drop.addEventListener("drop", (event) => {
    importRecording(event.dataTransfer.files[0]);
  });

  // A file dropped anywhere else must not replace Freya's window.
  ["dragover", "drop"].forEach((name) => {
    window.addEventListener(name, (event) => event.preventDefault());
  });
}

// Make sure Freya holds the chosen recording, then carry on with its id.
function withCloneRecording(next) {
  if (!cloneClip) {
    voiceMessage("Import a recording first.", true);
    return;
  }
  if (!$("clone-consent").checked) {
    voiceMessage("Confirm that you have the right to use this voice first.", true);
    return;
  }

  const transcript = $("clone-transcript").value;
  const key = [cloneClip.stamp, cloneStart(), transcript].join("|");
  if (cloneReference && cloneReference.key === key) {
    next(cloneReference.id);
    return;
  }

  stopListening();
  voiceMessage("Preparing the recording…");
  recordingSamples()
    .then((pcm) => {
      const bytes = pcm.buffer;
      for (let at = 0; at < bytes.byteLength; at += RECORDING_CHUNK) {
        socket.send(bytes.slice(at, at + RECORDING_CHUNK));
      }
      voiceSend(
        "reference",
        { sample_rate: RECORDING_RATE, consent: true, transcript },
        "Sending the recording…",
        (event) => {
          cloneReference = { key, id: event.reference.id };
          next(event.reference.id);
        },
      );
    })
    .catch(() => {
      voiceMessage("That recording could not be prepared.", true);
    });
}

function cloneSettings(reference) {
  const model = cloneModel();
  const settings = {
    model: model.id,
    language: $("clone-language").value,
    reference,
  };
  CLONE_SLIDERS.forEach((name) => {
    if (!$("clone-" + name + "-field").hidden) {
      settings[name] = Number($("clone-" + name).value);
    }
  });
  return settings;
}

function wireCloneAndDesign() {
  $("clone-engine").addEventListener("change", refreshCloneModels);
  $("clone-model").addEventListener("change", refreshCloneControls);
  $("design-engine").addEventListener("change", refreshDesignControls);

  CLONE_SLIDERS.forEach((name) => {
    const input = $("clone-" + name);
    input.addEventListener("input", () => {
      input.dataset.touched = "1";
      $("clone-" + name + "-value").textContent = Number(input.value).toFixed(2);
    });
  });

  $("clone-preview").addEventListener("click", () => {
    withCloneRecording((reference) => {
      voiceSend(
        "preview",
        {
          engine: $("clone-engine").value,
          kind: "clone",
          settings: cloneSettings(reference),
          text: $("clone-text").value,
        },
        "Generating speech in the cloned voice…" + SLOW_NOTE,
      );
    });
  });

  $("clone-save").addEventListener("click", () => {
    withCloneRecording((reference) => {
      voiceSend(
        "save",
        {
          engine: $("clone-engine").value,
          kind: "clone",
          settings: cloneSettings(reference),
          name: $("clone-name").value,
        },
        "Saving…",
      );
    });
  });

  $("design-generate").addEventListener("click", () => {
    const description = $("design-description").value;
    const language = $("design-language").value;
    const engine = $("design-engine").value;
    voiceSend(
      "design",
      {
        engine,
        settings: { description, language },
        text: $("design-text").value,
      },
      "Designing the voice…" + SLOW_NOTE,
      (event) => {
        designReference = { id: event.reference.id, engine, description, language };
        $("design-save").disabled = false;
        $("design-save").title = "";
      },
    );
  });

  $("design-save").addEventListener("click", () => {
    if (!designReference) return;
    voiceSend(
      "save",
      {
        engine: designReference.engine,
        kind: "design",
        name: $("design-name").value,
        settings: {
          description: designReference.description,
          language: designReference.language,
          reference: designReference.id,
          model: $("design-model").value,
        },
      },
      "Saving…",
      () => {
        designReference = null;
        $("design-save").disabled = true;
      },
    );
  });

  $("voice-free").addEventListener("click", () => {
    voiceSend("free", {}, "Unloading…");
  });
}

function showCloneAndDesign() {
  const cloners = readyEngines("clone");
  $("clone-form").hidden = !cloners.length;
  if (cloners.length) {
    fillSelect($("clone-engine"), engineOptions(cloners));
    refreshCloneModels();
    describeCloneClip();
    if (!$("clone-text").value) $("clone-text").value = voice.sample_text;
  }

  const designers = readyEngines("design");
  $("design-form").hidden = !designers.length;
  if (designers.length) {
    fillSelect($("design-engine"), engineOptions(designers));
    refreshDesignControls();
    if (!$("design-text").value) $("design-text").value = voice.sample_text;
  }

  $("voice-free").hidden = !voice.engines.some((engine) => engine.loaded);
}

function showVoice(next) {
  if (!next || !next.engines) return;
  voice = next;
  showCloneAndDesign();

  const preset = presetEngine();
  $("panel-preset").hidden = !preset;
  if (preset) {
    $("preset-engines").textContent = preset.name + ": " + preset.summary;
    fillSelect($("preset-language"), languageOptions(preset));
    refreshPresetVoices();
  }

  const blend = blendEngine();
  $("panel-blend").hidden = !blend;
  if (blend) {
    fillSelect($("blend-language"), languageOptions(blend));
    refreshBlendVoices();
  }

  fillEngineList("clone-engines", voice.sections.clone);
  fillEngineList("design-engines", voice.sections.design);

  fillSelect(
    $("play-engine"),
    voice.sections.playground
      .map(engineById)
      .filter(Boolean)
      .map((engine) => ({ value: engine.id, label: engine.name })),
  );
  refreshPlaygroundProfiles();
  if (!$("play-text").value) $("play-text").value = voice.sample_text;

  const list = $("profile-list");
  list.replaceChildren();
  voice.profiles.forEach((profile) => list.appendChild(profileRow(profile)));
  if (!voice.profiles.length) {
    list.appendChild(element("li", "", "No saved voices yet."));
  }
}

function presetSettings() {
  return {
    language: $("preset-language").value,
    voice: $("preset-voice").value,
    speed: Number($("preset-speed").value),
  };
}

function blendSettings() {
  const share = Number($("blend-mix").value);
  return {
    language: $("blend-language").value,
    speed: Number($("blend-speed").value),
    voices: [
      { voice: $("blend-a").value, weight: share },
      { voice: $("blend-b").value, weight: 100 - share },
    ],
  };
}

function wireVoice() {
  const speedLabel = (inputId, labelId) => {
    const update = () => {
      $(labelId).textContent = Number($(inputId).value).toFixed(2) + "x";
    };
    $(inputId).addEventListener("input", update);
    update();
  };
  speedLabel("preset-speed", "preset-speed-value");
  speedLabel("blend-speed", "blend-speed-value");

  $("blend-mix").addEventListener("input", () => {
    const share = Number($("blend-mix").value);
    $("blend-mix-value").textContent = share + "% / " + (100 - share) + "%";
  });

  $("preset-language").addEventListener("change", refreshPresetVoices);
  $("blend-language").addEventListener("change", refreshBlendVoices);
  $("play-engine").addEventListener("change", refreshPlaygroundProfiles);

  $("preset-preview").addEventListener("click", () => {
    const engine = presetEngine();
    if (engine) {
      voiceSend(
        "preview",
        { engine: engine.id, kind: "preset", settings: presetSettings() },
        "Generating a preview…",
      );
    }
  });

  $("preset-save").addEventListener("click", () => {
    const engine = presetEngine();
    if (engine) {
      voiceSend(
        "save",
        {
          engine: engine.id,
          kind: "preset",
          settings: presetSettings(),
          name: $("preset-name").value,
        },
        "Saving…",
      );
    }
  });

  $("blend-preview").addEventListener("click", () => {
    const engine = blendEngine();
    if (engine) {
      voiceSend(
        "preview",
        { engine: engine.id, kind: "blend", settings: blendSettings() },
        "Generating a preview…",
      );
    }
  });

  $("blend-save").addEventListener("click", () => {
    const engine = blendEngine();
    if (engine) {
      voiceSend(
        "save",
        {
          engine: engine.id,
          kind: "blend",
          settings: blendSettings(),
          name: $("blend-name").value,
        },
        "Saving…",
      );
    }
  });

  $("play-speak").addEventListener("click", () => {
    voiceSend(
      "speak",
      { profile: $("play-profile").value, text: $("play-text").value },
      "Generating speech…",
    );
  });
}

// -- images ----------------------------------------------------------

function addImage(image, newest) {
  $("gallery-empty").hidden = true;

  const card = element("figure", "card");
  const picture = element("img");
  picture.src = "/images/" + encodeURIComponent(image.id);
  picture.alt = image.prompt;
  picture.loading = "lazy";
  picture.addEventListener("click", () => openLightbox(image));

  const caption = element("figcaption", "", image.prompt);
  caption.appendChild(element("span", "when", when(image.created)));

  card.appendChild(picture);
  card.appendChild(caption);

  if (newest) {
    gallery.insertBefore(card, gallery.firstChild);
  } else {
    gallery.appendChild(card);
  }
}

// The same image, shown in the conversation where it was asked for.
function addChatImage(image) {
  const bubble = element("div", "message from-freya has-image");
  bubble.appendChild(element("span", "who", "Freya"));

  // The picture changes the height of the chat once it arrives, so
  // decide now whether the chat should stay at the bottom then.
  const stick = replaying || nearBottom(messages);

  const picture = element("img");
  picture.src = "/images/" + encodeURIComponent(image.id);
  picture.alt = image.prompt;
  picture.addEventListener("click", () => openLightbox(image));
  picture.addEventListener("load", () => {
    if (stick) messages.scrollTop = messages.scrollHeight;
  });

  bubble.appendChild(picture);
  bubble.appendChild(element("span", "caption", image.prompt));
  addToChat(bubble);
}

function openLightbox(image) {
  $("lightbox-image").src = "/images/" + encodeURIComponent(image.id);
  $("lightbox-image").alt = image.prompt;
  $("lightbox-caption").textContent = image.prompt;
  $("lightbox").hidden = false;
}

function closeLightbox() {
  $("lightbox").hidden = true;
  $("lightbox-image").removeAttribute("src");
}

// -- status ----------------------------------------------------------

function setPill(id, text, level) {
  const pill = $(id);
  pill.textContent = text;
  pill.classList.remove("is-good", "is-warn", "is-bad");
  if (level) pill.classList.add("is-" + level);
}

function showStatus(next) {
  status = next || {};

  const mic = {
    listening: ["Listening", "good"],
    muted: ["Muted", "warn"],
    off: ["Microphone off", "bad"],
  }[status.microphone] || ["Microphone", ""];
  setPill("pill-mic", mic[0], mic[1]);
  $("pill-mic").disabled = status.microphone === "off";
  $("pill-mic").title =
    status.microphone === "listening"
      ? "Listening for " + (status.names || []).join(", ") + ". Click to mute."
      : status.microphone === "muted"
        ? "Click to unmute."
        : "The microphone is not running.";

  setPill(
    "pill-model",
    status.model === "healthy" ? "Model ready" : "Model unavailable",
    status.model === "healthy" ? "good" : "bad",
  );

  const images = {
    healthy: ["Images ready", "good"],
    startable: ["Images on demand", "warn"],
    unavailable: ["Images unavailable", "bad"],
  }[status.images] || ["Images", ""];
  setPill("pill-images", images[0], images[1]);
}

// -- connection --------------------------------------------------------

function connect() {
  socket = new WebSocket("ws://" + location.host + "/ws");

  socket.addEventListener("open", () => {
    banner.hidden = true;
    retryDelay = 500;
  });

  socket.addEventListener("message", (message) => {
    let event;
    try {
      event = JSON.parse(message.data);
    } catch (error) {
      return;
    }

    if (event.type === "hello") {
      messages.querySelectorAll(".message, .notice").forEach((n) => n.remove());
      gallery.querySelectorAll(".card").forEach((n) => n.remove());
      $("chat-empty").hidden = false;
      $("gallery-empty").hidden = false;
      currentReply = null;
      consoleLines = [];
      replaying = true;
      event.history.forEach(showEvent);
      replaying = false;
      finishReply();
      event.images.forEach((image) => addImage(image, false));
      addConsoleLines(event.console || []);
      showVoice(event.voice);
      showStatus(event.status);
      messages.scrollTop = messages.scrollHeight;
      consoleOutput.scrollTop = consoleOutput.scrollHeight;
      return;
    }

    showEvent(event);
  });

  socket.addEventListener("close", () => {
    banner.hidden = false;
    finishReply();
    setTimeout(connect, retryDelay);
    retryDelay = Math.min(retryDelay * 2, 5000);
  });
}

// -- controls ----------------------------------------------------------

function autoGrow(box) {
  box.style.height = "auto";
  box.style.height = Math.min(box.scrollHeight, 180) + "px";
}

function wireComposer(formId, inputId, deliver) {
  const form = $(formId);
  const input = $(inputId);

  const submit = () => {
    const text = input.value.trim();
    if (!text) return;
    if (deliver(text)) {
      input.value = "";
      autoGrow(input);
    }
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submit();
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  });

  input.addEventListener("input", () => autoGrow(input));
}

const VIEW_INPUT = {
  chat: "chat-input",
  images: "image-input",
  voice: "preset-language",
  console: "console-input",
};

function showView(name) {
  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.view === name;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("is-active", view.id === "view-" + name);
  });
  if (name === "images") $("images-badge").hidden = true;
  $(VIEW_INPUT[name]).focus();
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => showView(tab.dataset.view));
});

wireComposer("chat-form", "chat-input", submitText);
wireComposer("console-form", "console-input", submitText);
wireComposer("image-form", "image-input", (text) => send({ type: "image", text }));

$("stop-speaking").addEventListener("click", () => send({ type: "interrupt" }));

$("console-hide").addEventListener("click", () => showConsoleTab(false));

$("pill-mic").addEventListener("click", () => {
  send({ type: "mute", muted: status.microphone === "listening" });
});

$("lightbox").addEventListener("click", closeLightbox);

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeLightbox();
});

if (recall(CONSOLE_SHOWN_KEY)) $("tab-console").hidden = false;

wireVoice();
wireCloneAndDesign();
wireImport();

connect();
$("chat-input").focus();
