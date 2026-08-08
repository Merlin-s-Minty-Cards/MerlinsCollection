# T5 — Camera barcode fallback

**RFC:** 0009 §8 · **Layer:** frontend · **Depends on:** T4 · **Blocks:** nothing

**Droppable.** T4 already delivers a working intake flow. This adds show-floor
convenience: scanning with a phone when the wedge scanner is on the desk at home.
If the branch is running long, cut this and keep the feature shipped.

## Files

- **Create:** `frontend/components/admin/slabs/CameraScanner.tsx`
- **Modify:** `frontend/components/admin/slabs/ScanInput.tsx` — add the "Use camera"
  button
- **Test:** `frontend/components/admin/slabs/__tests__/CameraScanner.test.tsx`

## The browser problem

`BarcodeDetector` is a native API with **no Safari or Firefox support**. Since this
is most useful on a phone at a show, and iPhone Safari is the likely device, the
fallback is not optional.

Strategy:

1. Feature-detect `window.BarcodeDetector`. Use it when present — zero bundle cost,
   native performance.
2. Otherwise **dynamically import** a wasm decoder (`@zxing/browser` or
   `barcode-detector` polyfill). Dynamic import is required: this is a heavy
   dependency and it must not enter the main admin bundle for the majority of
   sessions that never open the camera.
3. If neither works, hide the camera button entirely and say why. A dead button is
   worse than no button.

Check the decoder's bundle size before committing to it and record the number in
`progress.md` — the admin route's weight is a real cost.

## Behavior

- The camera button opens a viewfinder overlay; closing it stops **all** tracks.
  A camera left running is a battery and privacy problem, and on iOS it is very
  visible.
- On a successful decode: emit the same `onScan` callback `ScanInput` already uses,
  so the entire staging pipeline from T4 is reused untouched. **Do not build a second
  intake path.**
- Decode continuously until a barcode is found or the operator closes it.
- Requires HTTPS (or localhost) — `getUserMedia` is unavailable otherwise. Detect
  and explain rather than failing silently.
- Permission denied → a clear message with a hint to re-enable it in browser
  settings, and the manual input stays available.

## PSA barcode formats

PSA labels have carried more than one symbology over the years, and older slabs
differ from current ones. **Do not restrict the decoder to a single format** — accept
the common 1D set plus QR, and let the cert number validate downstream. If a decode
produces something that is not a plausible cert number, show it to the operator
rather than discarding it; they can correct it by hand.

## RED — write these first, confirm they fail, then STOP

```bash
cd frontend && npx vitest run components/admin/slabs --reporter=verbose
```

Mock `navigator.mediaDevices.getUserMedia` and `window.BarcodeDetector`; **never**
open a real camera in a test.

1. With `BarcodeDetector` present, it is used and no dynamic import fires.
2. With it absent, the fallback module is imported.
3. With neither available, the camera button is not rendered.
4. A successful decode calls `onScan` with the decoded value.
5. Closing the overlay calls `stop()` on every track.
6. Unmounting while the camera is open also stops every track.
7. Permission denial renders the explanatory message and does not throw.
8. Non-secure context renders the HTTPS explanation and hides the button.
9. A decode emits `onScan` exactly once, even if the decode loop fires repeatedly
   before the overlay closes.

## GREEN

Only after the owner confirms failure.

## Manual check

Test on the actual phone the owner would use at a show, on a real slab, in
show-hall lighting. Bench testing on a laptop webcam proves very little here.

## Commit

```bash
git add frontend/components/admin/slabs frontend/package.json
git commit -m "feat(slabs): camera barcode fallback for show-floor scanning"
```

Record the added bundle weight in [`progress.md`](progress.md).
