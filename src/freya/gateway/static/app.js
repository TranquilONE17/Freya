"use strict";

// Everything Freya sends is shown with textContent, never as HTML: her
// replies and tool results are not trusted markup.

const $ = (id) => document.getElementById(id);

const messages = $("messages");
const gallery = $("gallery");
const banner = $("banner");
const imageWorking = $("image-working");

let socket = null;
let retryDelay = 500;
let currentReply = null;
let status = {};

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
      imageWorking.hidden = true;
      addImage(event.image, true);
      if (!$("view-images").classList.contains("is-active")) {
        $("images-badge").hidden = false;
      }
      break;

    case "image_failed":
      imageWorking.hidden = true;
      break;

    case "status":
      showStatus(event.status);
      break;

    case "error":
      addToChat(element("p", "notice", event.text));
      break;
  }
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
      event.history.forEach(showEvent);
      finishReply();
      event.images.forEach((image) => addImage(image, false));
      showStatus(event.status);
      messages.scrollTop = messages.scrollHeight;
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

function wireComposer(formId, inputId, type) {
  const form = $(formId);
  const input = $(inputId);

  const submit = () => {
    const text = input.value.trim();
    if (!text) return;
    if (send({ type, text })) {
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
  $(name === "images" ? "image-input" : "chat-input").focus();
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => showView(tab.dataset.view));
});

wireComposer("chat-form", "chat-input", "say");
wireComposer("image-form", "image-input", "image");

$("stop-speaking").addEventListener("click", () => send({ type: "interrupt" }));

$("pill-mic").addEventListener("click", () => {
  send({ type: "mute", muted: status.microphone === "listening" });
});

$("lightbox").addEventListener("click", closeLightbox);

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeLightbox();
});

connect();
$("chat-input").focus();
