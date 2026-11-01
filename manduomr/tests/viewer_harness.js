// Minimal Apps Script service stand-ins so viewer/Code.gs runs unchanged in a browser JS engine.
// window.__files: {id: {name, text|base64, mime}}, window.__folders: {id: {name: fileId}}
(function () {
  function sha256Bytes(bytes) {
    var K = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
    var H = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
    var l = bytes.length, padded = bytes.slice();
    padded.push(0x80); while (padded.length % 64 !== 56) padded.push(0);
    var bits = l * 8; for (var i = 7; i >= 0; i--) padded.push(i >= 4 ? 0 : (bits >>> (i * 8)) & 255);
    function r(x, n) { return (x >>> n) | (x << (32 - n)); }
    for (var o = 0; o < padded.length; o += 64) {
      var w = [];
      for (var t = 0; t < 64; t++) {
        if (t < 16) w[t] = (padded[o+t*4] << 24) | (padded[o+t*4+1] << 16) | (padded[o+t*4+2] << 8) | padded[o+t*4+3];
        else { var s0 = r(w[t-15],7) ^ r(w[t-15],18) ^ (w[t-15] >>> 3), s1 = r(w[t-2],17) ^ r(w[t-2],19) ^ (w[t-2] >>> 10); w[t] = (w[t-16] + s0 + w[t-7] + s1) | 0; }
      }
      var a=H[0],b=H[1],c=H[2],d=H[3],e=H[4],f=H[5],g=H[6],h=H[7];
      for (t = 0; t < 64; t++) {
        var t1 = (h + (r(e,6) ^ r(e,11) ^ r(e,25)) + ((e & f) ^ (~e & g)) + K[t] + w[t]) | 0;
        var t2 = ((r(a,2) ^ r(a,13) ^ r(a,22)) + ((a & b) ^ (a & c) ^ (b & c))) | 0;
        h=g; g=f; f=e; e=(d+t1)|0; d=c; c=b; b=a; a=(t1+t2)|0;
      }
      H=[(H[0]+a)|0,(H[1]+b)|0,(H[2]+c)|0,(H[3]+d)|0,(H[4]+e)|0,(H[5]+f)|0,(H[6]+g)|0,(H[7]+h)|0];
    }
    var out = []; H.forEach(function (v) { for (var i = 3; i >= 0; i--) out.push((v >>> (i * 8)) & 255); });
    return out;
  }
  function utf8(text) { return Array.from(new TextEncoder().encode(text)); }
  function blob(id) {
    var f = window.__files[id]; if (!f) throw new Error('no file ' + id);
    return {
      getDataAsString: function () { return f.text; },
      getBytes: function () { var raw = atob(f.base64); var out = []; for (var i = 0; i < raw.length; i++) { var v = raw.charCodeAt(i); out.push(v > 127 ? v - 256 : v); } return out; },
      getContentType: function () { return f.mime || 'application/octet-stream'; }
    };
  }
  window.DriveApp = {
    getFileById: function (id) { return { getBlob: function () { return blob(id); } }; },
    getFolderById: function (id) {
      return { getFilesByName: function (name) {
        var fid = (window.__folders[id] || {})[name], used = false;
        return { hasNext: function () { return !!fid && !used; }, next: function () { used = true; return window.DriveApp.getFileById(fid); } };
      } };
    }
  };
  window.Utilities = {
    DigestAlgorithm: { SHA_256: 'SHA_256' }, Charset: { UTF_8: 'UTF_8' },
    computeDigest: function (alg, text) { return sha256Bytes(utf8(text)).map(function (b) { return b > 127 ? b - 256 : b; }); },
    base64Encode: function (signed) { var s = ''; signed.forEach(function (b) { s += String.fromCharCode((b + 256) % 256); }); return btoa(s); }
  };
  var props = {};
  window.__props = props;
  window.PropertiesService = { getScriptProperties: function () { return {
    getProperty: function (k) { return Object.prototype.hasOwnProperty.call(props, k) ? props[k] : null; },
    setProperty: function (k, v) { props[k] = String(v); },
    deleteProperty: function (k) { delete props[k]; } }; } };
  window.LockService = { getScriptLock: function () { return { waitLock: function () {}, releaseLock: function () {} }; } };
  window.__now = Date.now();
  Date.now = function () { return window.__now; };
})();
