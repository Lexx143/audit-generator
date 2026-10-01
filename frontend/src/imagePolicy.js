export function visibleCaseImage(caseData, generateIllustrations) {
  if (generateIllustrations) return caseData.image_b64;
  const automatic = ['generated', 'library'].includes(caseData.image_source)
    || (!caseData.image_source && caseData.image_reusable);
  return automatic ? null : caseData.image_b64;
}
