/* Currencies, quests and backups. */

async function loadPlayer() {
  if (!S.path) return;
  const p = await api('/api/player?path=' + encodeURIComponent(S.path));
  for (const k of ['units', 'nanites', 'quicksilver']) $('#p_' + k).value = p[k];
}
$('#pSave').onclick = () => guard(async () => {
  const body = {path: S.path}; for (const k of ['units', 'nanites', 'quicksilver']) body[k] = Number($('#p_' + k).value);
  await post('/api/player', body); toast('Currencies saved. Backup made.');
});
