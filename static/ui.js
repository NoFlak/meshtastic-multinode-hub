document.addEventListener('DOMContentLoaded', () => {
  const scanBtn = document.getElementById('scanBtn')
  const commitBtn = document.getElementById('commitBtn')
  const undoBtn = document.getElementById('undoBtn')
  const status = document.getElementById('status')
  const candidates = document.getElementById('candidates')
  const output = document.getElementById('output')

  function setStatus(txt) { status.textContent = txt }
  function appendOutput(txt) { output.textContent += txt + '\n' }

  scanBtn.addEventListener('click', async () => {
    setStatus('Discovering...')
    candidates.innerHTML = ''
    const res = await fetch('/api/discover')
    const data = await res.json()
    setStatus('Done')
    appendOutput(JSON.stringify(data, null, 2))
    // show candidates
    const list = []
    for (const c of (data.com_ports || [])) list.push(c.device)
    for (const b of (data.ble_devices || [])) if (b.address) list.push(b.address)
    candidates.innerHTML = list.map(d => `<div class="candidate">${d} <button data-device="${d}" class="validate">Validate</button></div>`).join('\n')
    for (const btn of document.querySelectorAll('.validate')) {
      btn.addEventListener('click', async (ev) => {
        const dev = ev.target.dataset.device
        setStatus('Validating ' + dev)
        const r = await fetch('/api/validate', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({device: dev})})
        const jr = await r.json()
        appendOutput(`Validate ${dev}: ${JSON.stringify(jr)}`)
        setStatus('')
      })
    }
  })

  commitBtn.addEventListener('click', async () => {
    setStatus('Committing (dry-run)...')
    const r = await fetch('/api/commit', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({auto_commit:false})})
    const jr = await r.json()
    appendOutput('Commit result: ' + JSON.stringify(jr, null, 2))
    setStatus('')
  })

  undoBtn.addEventListener('click', async () => {
    setStatus('Undoing last commit...')
    const r = await fetch('/api/undo', {method: 'POST'})
    const jr = await r.json()
    appendOutput('Undo result: ' + JSON.stringify(jr))
    setStatus('')
  })
})
