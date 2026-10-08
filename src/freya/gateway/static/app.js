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

// Typed text is a message for Freya unless it starts with a slash, in
// which case it is one of her commands. Opening the Console tab is the
// one command handled here in the window.
function submitText(text) {
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

function voiceSend(action, fields, working) {
  voiceRequests += 1;
  const request = "v" + voiceRequests;
  if (send({ type: "voice", action, request, ...fields })) {
    voicePending = request;
    voiceMessage(working || "Working…");
  }
}

function voiceResult(event) {
  showVoice(event.state);

  // Another window's request only refreshes what is shown here.
  if (event.request !== voicePending) return;
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

function showVoice(next) {
  if (!next || !next.engines) return;
  voice = next;

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

connect();
$("chat-input").focus();
