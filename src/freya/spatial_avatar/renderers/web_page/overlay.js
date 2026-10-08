// Draws the face of Freya's chosen avatar model in the overlay's round
// window.
//
// This page only draws. Where she is, how big she is, what she is
// looking toward, and whether she is speaking are all decided by the
// overlay program, which tells this page with freya.set(...). The page
// sends nothing back and loads nothing from outside the overlay.
//
// The model file is untrusted. It is only ever parsed as a 3D model.

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";

const canvas = document.getElementById("avatar");

// What the overlay last said about her.
const told = {
  expression: "neutral",
  speaking: false,
  level: 0,
  appearance: "realistic",
  fps: 30,
  // Which way to look, as a direction on screen (x right, y up), and
  // how far the gesture has got, from 0 to 1.
  look: null,
  wave: false,
};

// The overlay's expressions, as mixes of the ones a VRM model has.
const EXPRESSIONS = {
  neutral: {},
  happy: { happy: 0.8 },
  thinking: { lookUp: 0.6, relaxed: 0.3 },
  surprised: { surprised: 0.9 },
  concerned: { sad: 0.6 },
};

// Her arms hang down from the pose the model is made in. They are out
// of view, but her shoulders are not.
const ARM_DOWN = 1.2;

window.freya = {
  ready: false,
  error: "",
  set(next) {
    Object.assign(told, next);
    canvas.classList.toggle("is-holographic", told.appearance === "holographic");
  },
};

function bone(vrm, name) {
  return vrm.humanoid ? vrm.humanoid.getNormalizedBoneNode(name) : null;
}

// Ease a value toward a goal, at a rate that does not depend on the
// frame rate.
function toward(now, goal, seconds, speed) {
  return now + (goal - now) * Math.min(1, seconds * speed);
}

async function start() {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  scene.add(new THREE.AmbientLight(0xffffff, 1.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.8);
  sun.position.set(1, 2, 2);
  scene.add(sun);

  const camera = new THREE.PerspectiveCamera(22, 1, 0.05, 30);

  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));
  const gltf = await loader.loadAsync("model.vrm");
  const vrm = gltf.userData.vrm;
  if (!vrm) throw new Error("The file is not a VRM avatar.");

  VRMUtils.rotateVRM0(vrm);
  scene.add(vrm.scene);

  const head = bone(vrm, "head");
  const neck = bone(vrm, "neck");
  const leftArm = bone(vrm, "leftUpperArm");
  const rightArm = bone(vrm, "rightUpperArm");
  if (leftArm) leftArm.rotation.z = -ARM_DOWN;
  if (rightArm) rightArm.rotation.z = ARM_DOWN;
  vrm.update(0);

  // Frame her head: from the head bone (the base of the skull) to the
  // top of the figure, with room for her hair.
  const box = new THREE.Box3().setFromObject(vrm.scene);
  const top = box.max.y;
  const base = new THREE.Vector3(0, top - (top - box.min.y) * 0.13, 0);
  if (head) head.getWorldPosition(base);
  const tall = Math.max(top - base.y, 0.05);
  const middle = new THREE.Vector3(base.x, base.y + tall * 0.46, base.z);
  const distance = (tall * 1.55) / 2 / Math.tan((camera.fov * Math.PI) / 360);
  camera.position.set(middle.x, middle.y, middle.z + distance);
  camera.lookAt(middle);

  function fit() {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;

    const current = renderer.getSize(new THREE.Vector2());
    if (current.x === width && current.y === height) return;

    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  const face = {};
  const turn = { x: 0, y: 0 };
  let mouth = 0;
  let last = performance.now();
  let drawn = 0;
  let blinkAt = 2 + Math.random() * 3;

  function draw(now) {
    requestAnimationFrame(draw);

    // No faster than the overlay asks for.
    if (now - drawn < 1000 / Math.max(told.fps, 1) - 2) return;
    drawn = now;

    const seconds = Math.min((now - last) / 1000, 0.1);
    last = now;
    const time = now / 1000;
    fit();

    const manager = vrm.expressionManager;
    if (manager) {
      const wanted = EXPRESSIONS[told.expression] || {};
      const names = new Set(Object.keys(face).concat(Object.keys(wanted)));
      names.forEach((name) => {
        face[name] = toward(face[name] || 0, wanted[name] || 0, seconds, 8);
        if (manager.getExpression(name)) manager.setValue(name, face[name]);
      });

      blinkAt -= seconds;
      let blink = 0;
      if (blinkAt < 0) {
        blink = 1;
        if (blinkAt < -0.12) blinkAt = 2.5 + Math.random() * 4;
      }
      if (manager.getExpression("blink")) manager.setValue("blink", blink);

      // While she speaks her mouth opens and closes, more for louder
      // speech as far as that is known.
      const open = told.speaking
        ? (0.25 + 0.75 * Math.abs(Math.sin(time * 9))) * (0.4 + 0.6 * (told.level || 0.6))
        : 0;
      mouth = toward(mouth, open, seconds, 18);
      if (manager.getExpression("aa")) manager.setValue("aa", mouth);
    }

    // She turns her head toward what she is pointing at, and nods
    // while she waves.
    const goal = { x: 0, y: 0 };
    if (told.look && told.look.amount > 0) {
      const length = Math.hypot(told.look.x, told.look.y) || 1;
      goal.y = (told.look.x / length) * 0.5 * told.look.amount;
      goal.x = (-told.look.y / length) * 0.3 * told.look.amount;
    } else if (told.wave) {
      goal.x = 0.08 * Math.sin(time * 6);
    }
    turn.x = toward(turn.x, goal.x, seconds, 6);
    turn.y = toward(turn.y, goal.y, seconds, 6);

    if (head) {
      head.rotation.y = turn.y * 0.7 + 0.04 * Math.sin(time * 0.5);
      head.rotation.x = turn.x * 0.7 + 0.02 * Math.sin(time * 0.37);
    }
    if (neck) {
      neck.rotation.y = turn.y * 0.3;
      neck.rotation.x = turn.x * 0.3;
    }

    vrm.update(seconds);
    renderer.render(scene, camera);
  }

  requestAnimationFrame(draw);
  window.freya.ready = true;
}

start().catch((error) => {
  window.freya.error = String((error && error.message) || error);
});
