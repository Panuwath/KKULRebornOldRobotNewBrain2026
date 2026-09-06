/**
 * Zenbo Face Texture Generator
 * Procedurally draws Zenbo Junior's facial expressions onto a 2D HTML5 Canvas
 */

(function(window) {
  'use strict';

  var FACES = [
    'DEFAULT_STILL', 'HAPPY', 'PLEASED', 'PROUD', 'CONFIDENT',
    'INTERESTED', 'EXPECTING', 'SERIOUS', 'SINGING'
  ];

  function normalizeFace(name) {
    if (!name) return 'DEFAULT_STILL';
    var upper = String(name).toUpperCase().trim();
    if (upper.indexOf('_ADV') !== -1) {
      upper = upper.replace('_ADV', '');
    }
    for (var i = 0; i < FACES.length; i++) {
      if (FACES[i] === upper) return upper;
    }
    return 'DEFAULT_STILL';
  }

  function draw(canvas, faceName, opts) {
    if (!canvas) return;
    var ctx = canvas.getContext('2d');
    if (!ctx) return;

    opts = opts || {};
    var face = normalizeFace(faceName);
    var w = canvas.width || 256;
    var h = canvas.height || 128;

    // Background visor glass
    ctx.fillStyle = '#060b19';
    ctx.fillRect(0, 0, w, h);

    // Subtle inner visor glow
    var grad = ctx.createRadialGradient(w / 2, h / 2, 10, w / 2, h / 2, w / 1.8);
    grad.addColorStop(0, 'rgba(6, 182, 212, 0.12)');
    grad.addColorStop(1, 'rgba(2, 6, 23, 0.95)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, w, h);

    var eyeColor = '#38bdf8';
    var eyeGlow = '#0284c7';
    var blushColor = 'rgba(244, 63, 94, 0.45)';

    var leftEyeX = w * 0.32;
    var rightEyeX = w * 0.68;
    var eyeY = h * 0.48;

    // Blushes on cheeks
    if (face === 'HAPPY' || face === 'PLEASED' || face === 'SINGING' || face === 'EXPECTING') {
      ctx.fillStyle = blushColor;
      ctx.beginPath();
      ctx.ellipse(leftEyeX - 18, eyeY + 22, 14, 7, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.ellipse(rightEyeX + 18, eyeY + 22, 14, 7, 0, 0, Math.PI * 2);
      ctx.fill();
    }

    // Draw Eyes
    ctx.fillStyle = eyeColor;
    ctx.shadowColor = eyeGlow;
    ctx.shadowBlur = 10;
    ctx.lineWidth = 6;
    ctx.strokeStyle = eyeColor;
    ctx.lineCap = 'round';

    if (face === 'HAPPY' || face === 'PLEASED' || face === 'SINGING') {
      // Crescent happy eyes (^ ^)
      ctx.beginPath();
      ctx.arc(leftEyeX, eyeY + 8, 20, Math.PI * 1.15, Math.PI * 1.85, false);
      ctx.stroke();

      ctx.beginPath();
      ctx.arc(rightEyeX, eyeY + 8, 20, Math.PI * 1.15, Math.PI * 1.85, false);
      ctx.stroke();
    } else if (face === 'SERIOUS') {
      // Focused narrower eyes
      ctx.fillRect(leftEyeX - 18, eyeY - 8, 36, 16);
      ctx.fillRect(rightEyeX - 18, eyeY - 8, 36, 16);
    } else {
      // Big friendly oval eyes
      ctx.beginPath();
      ctx.ellipse(leftEyeX, eyeY, 16, 22, 0, 0, Math.PI * 2);
      ctx.fill();

      ctx.beginPath();
      ctx.ellipse(rightEyeX, eyeY, 16, 22, 0, 0, Math.PI * 2);
      ctx.fill();

      // Catchlights (sparkles in pupils)
      ctx.shadowBlur = 0;
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.arc(leftEyeX - 5, eyeY - 6, 6, 0, Math.PI * 2);
      ctx.arc(rightEyeX - 5, eyeY - 6, 6, 0, Math.PI * 2);
      ctx.fill();

      ctx.beginPath();
      ctx.arc(leftEyeX + 6, eyeY + 7, 3, 0, Math.PI * 2);
      ctx.arc(rightEyeX + 6, eyeY + 7, 3, 0, Math.PI * 2);
      ctx.fill();
    }

    // Draw Mouth
    ctx.shadowBlur = 6;
    ctx.strokeStyle = eyeColor;
    ctx.fillStyle = eyeColor;
    ctx.lineWidth = 4;

    var mouthY = h * 0.76;
    if (face === 'HAPPY' || face === 'SINGING') {
      ctx.beginPath();
      ctx.arc(w / 2, mouthY - 4, 14, 0.1 * Math.PI, 0.9 * Math.PI, false);
      ctx.fill();
    } else if (face === 'EXPECTING' || face === 'INTERESTED') {
      ctx.beginPath();
      ctx.arc(w / 2, mouthY, 7, 0, Math.PI * 2);
      ctx.fill();
    } else if (face === 'PROUD' || face === 'CONFIDENT') {
      ctx.beginPath();
      ctx.arc(w / 2 + 5, mouthY - 5, 14, 0.15 * Math.PI, 0.7 * Math.PI, false);
      ctx.stroke();
    } else if (face === 'SERIOUS') {
      ctx.beginPath();
      ctx.moveTo(w / 2 - 12, mouthY);
      ctx.lineTo(w / 2 + 12, mouthY);
      ctx.stroke();
    } else {
      // Default subtle smile
      ctx.beginPath();
      ctx.arc(w / 2, mouthY - 6, 12, 0.2 * Math.PI, 0.8 * Math.PI, false);
      ctx.stroke();
    }

    ctx.shadowBlur = 0;
  }

  window.ZenboFaceTexture = {
    FACES: FACES,
    normalizeFace: normalizeFace,
    draw: draw
  };
})(typeof window !== 'undefined' ? window : this);
