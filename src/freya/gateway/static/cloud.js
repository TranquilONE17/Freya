"use strict";

// The Cloud tab: which cloud models Freya may use, what may be sent to
// them, and the owner's own record of what was sent. Everything shown
// here is placed on the page as text, never as markup.

(() => {
  const byId = (id) => document.getElementById("cloud-" + id);
  let requests = 0;
  let loaded = false;

  const LISTS = [
    ["not_private_phrases", "not-private", "phrase"],
    ["not_private_memories", "not-private", "memory"],
    ["always_private_phrases", "always-private", "phrase"],
    ["always_private_memories", "always-private", "memory"],
  ];

  function node(tag, className, text) {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (text !== undefined) result.textContent = text;
    return result;
  }

  function say(text, isError) {
    const line = byId("message");
    line.textContent = text;
    line.classList.toggle("is-error", Boolean(isError));
  }

  function ask(action, fields, working) {
    requests += 1;
    if (send({type: "cloud", action, request: "c" + requests, ...(fields || {})})) {
      say(working || "Saving…");
    } else {
      say("Not connected to Freya.", true);
    }
  }

  function showProviders(providers) {
    const box = byId("providers");
    box.replaceChildren();
    providers.forEach((provider) => {
      const label = node("label", "check");
      const input = node("input");
      input.type = "checkbox";
      input.checked = provider.enabled;
      input.addEventListener("change", () => {
        ask("provider", {name: provider.name, enabled: input.checked});
      });
      label.append(input, node("span", "", provider.label));
      if (!provider.available) {
        label.append(node("span", "tag", "not set up yet"));
      }
      box.append(label);
    });
  }

  function showMaterial(material, settings) {
    const names = {allowed: "Allowed", ask: "Ask me first", never: "Never"};
    const box = byId("material");
    box.replaceChildren();
    material.forEach((entry) => {
      const label = node("label", "", entry.label);
      const select = node("select");
      settings.forEach((setting) => {
        const option = node("option", "", names[setting] || setting);
        option.value = setting;
        option.selected = setting === entry.setting;
        select.append(option);
      });
      select.addEventListener("change", () => {
        ask("material", {kind: entry.kind, setting: select.value});
      });
      label.append(select);
      box.append(label);
    });
  }

  function showBars(bars) {
    ["low", "normal", "high"].forEach((value) => {
      byId("bar-" + value).value = Math.round(Number(bars[value]) * 100);
    });
  }

  function showCorrections(corrections) {
    const boxes = {
      "not-private": byId("not-private"),
      "always-private": byId("always-private"),
    };
    Object.values(boxes).forEach((box) => box.replaceChildren());
    LISTS.forEach(([name, list, what]) => {
      (corrections[name] || []).forEach((entry) => {
        const row = node("li");
        const about = node("div", "about");
        about.append(node(
          "span", "said", what === "memory" ? "Memory " + entry : entry,
        ));
        const remove = node("button", "ghost", "Remove");
        remove.type = "button";
        remove.addEventListener("click", () => {
          ask("unmark", {list: name, entry});
        });
        row.append(about, remove);
        boxes[list].append(row);
      });
    });
    Object.values(boxes).forEach((box) => {
      if (!box.children.length) box.append(node("li", "panel-note", "Nothing here."));
    });
  }

  function showSent(sent) {
    const box = byId("sent");
    box.replaceChildren();
    if (!sent.length) {
      box.append(node("li", "panel-note", "Nothing has been sent."));
      return;
    }
    sent.forEach((entry) => {
      const row = node("li");
      const about = node("div", "about");
      about.append(node(
        "span", "panel-note",
        String(entry.at || "").slice(0, 16).replace("T", " ") +
          " · " + entry.provider + " · " + entry.outcome,
      ));
      about.append(node("pre", "said", entry.text));
      row.append(about);
      box.append(row);
    });
  }

  function show(state) {
    showProviders(state.providers || []);
    showMaterial(state.material || [], state.settings || []);
    showBars(state.bars || {});
    showCorrections(state.corrections || {});
    const count = Number(state.sent_count) || 0;
    byId("sent-count").textContent =
      count === 1 ? "1 brief" : count + " briefs";
  }

  window.addEventListener("freya-cloud", (event) => {
    const answer = event.detail || {};
    if (answer.state) show(answer.state);
    if (Array.isArray(answer.sent)) showSent(answer.sent);
    say(answer.error || "", Boolean(answer.error));
  });

  window.addEventListener("freya-view", (event) => {
    if (event.detail === "cloud" && !loaded) {
      loaded = true;
      ask("state", {}, "Loading…");
    }
  });

  byId("bars-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const bars = {};
    ["low", "normal", "high"].forEach((value) => {
      bars[value] = Number(byId("bar-" + value).value) / 100;
    });
    ask("bars", {bars});
  });

  byId("mark-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const value = byId("mark-value").value.trim();
    if (!value) return;
    const fields = {list: byId("mark-list").value};
    if (byId("mark-what").value === "memory") fields.memory = value;
    else fields.phrase = value;
    ask("mark", fields);
    byId("mark-value").value = "";
  });

  byId("sent-show").addEventListener("click", () => {
    ask("sent", {}, "Loading…");
  });
})();
