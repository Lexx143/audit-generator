import { test } from 'node:test';
import assert from 'node:assert/strict';
import { visibleCaseImage } from './imagePolicy.js';

test('turning illustrations off excludes generated/library/legacy illustrations, preserving uploads', () => {
  for (const image_source of ['generated', 'library']) {
    assert.equal(visibleCaseImage({image_b64: 'image', image_source}, false), null);
    assert.equal(visibleCaseImage({image_b64: 'image', image_source}, true), 'image');
  }
  assert.equal(visibleCaseImage({image_b64: 'legacy', image_reusable: true}, false), null);
  assert.equal(visibleCaseImage({image_b64: 'manual', image_source: 'uploaded', image_reusable: true}, false), 'manual');
  assert.equal(visibleCaseImage({image_b64: 'photo', image_reusable: false}, false), 'photo');
});
