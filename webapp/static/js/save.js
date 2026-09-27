/* Export, import and the raw save editor. */
/* Pointing the tool at the game, for people whose copy is not where it usually lives. */
async function useGameFolder(folder) {
  if (!folder) throw new Error('Pick the folder No Man\'s Sky is installed in.');
  toast('Reading the game files, this takes a moment...');
  const r = await post('/api/gamedir', {path: folder});
  showBanner(`Using the game at ${r.nms_dir}.`, false);
  await loadHealth(false);
  await loadShips().catch(() => {});
}
$('#hPick').onclick = () => guard
