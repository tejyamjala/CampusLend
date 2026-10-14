const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const seed = {
  equipment: [
    { id: 1, name: 'MacBook Air M2', category: 'Laptop', owner: 'Meera Shah', initials: 'MS', visual: 'laptop', tone: 'purple', availability: 'Available', meta: '2 available', note: 'Great for project builds and presentations.', rate: '₹80 / day', availableFrom: '2026-10-15' },
    { id: 2, name: 'JBL Flip 6', category: 'Audio', owner: 'Kabir Menon', initials: 'KM', visual: 'speaker', tone: 'blue', availability: 'Available', meta: '1 available', note: 'Pick up from the student centre.', rate: '₹30 / day', availableFrom: '2026-10-15' },
    { id: 3, name: 'Sony α6400', category: 'Camera', owner: 'Rhea Kapoor', initials: 'RK', visual: 'camera', tone: 'tan', availability: 'Available', meta: 'Available', note: 'Includes 16–50mm kit lens.', rate: '₹120 / day', availableFrom: '2026-10-17' },
    { id: 4, name: 'Anker USB-C Hub', category: 'Accessories', owner: 'Aarav Rao', initials: 'AR', visual: 'hub', tone: 'gray', availability: 'Lent out', meta: 'Back in 2d', note: 'HDMI + 3 USB ports.', rate: 'Free', availableFrom: '2026-10-16' }
  ],
  requests: [
    { id: 1, title: 'Looking for a DSLR for fest coverage', person: 'Dev Kulkarni', initials: 'DK', time: 'Needed this weekend', category: 'Camera', duration: '2 days', detail: 'Would love to borrow a DSLR for our media team’s cultural fest coverage.' },
    { id: 2, title: 'Need an HDMI adapter for a demo', person: 'Ananya Iyer', initials: 'AI', time: 'Needed tomorrow', category: 'Accessories', duration: '1 day', detail: 'Presenting a product prototype at 10am. Can pick up anywhere on North Campus.' },
    { id: 3, title: 'Speaker for a society event', person: 'Ritvik Shah', initials: 'RS', time: 'Needed next week', category: 'Audio', duration: '4 hours', detail: 'Small indoor event for around 40 people. Happy to collect and return same day.' }
  ],
  rentals: [
    { id: 'CL-2048', name: 'MacBook Air M2', category: 'Laptop', owner: 'Meera Shah', role: 'borrower', status: 'On track', due: 'Friday, 16 Oct · 6:00 PM', dueAt: '2026-10-16T18:00:00+05:30', progress: 61, location: 'Library · Floor 2', days: '2d 04h', penalty: '—' },
    { id: 'CL-2039', name: 'Anker USB-C Hub', category: 'Accessories', owner: 'Aarav Rao', role: 'lender', status: 'Due soon', due: 'Tomorrow, 15 Oct · 2:00 PM', dueAt: '2026-10-15T14:00:00+05:30', progress: 86, location: 'Engineering Block', days: '18h', penalty: '—' },
    { id: 'CL-1988', name: 'Logitech webcam', category: 'Accessories', owner: 'Ishita Sen', role: 'borrower', status: 'Overdue', due: 'Mon, 12 Oct · 5:00 PM', dueAt: '2026-10-12T17:00:00+05:30', progress: 100, location: 'Design studio', days: '3d overdue', penalty: '₹90' }
  ],
  history: [
    { name: 'USB-C hub', person: 'Arjun Das', date: '12 Oct 2026', type: 'Lent', status: 'Completed', penalty: '—' },
    { name: 'MacBook Air M2', person: 'Meera Shah', date: '08 Oct 2026', type: 'Borrowed', status: 'Active', penalty: '—' },
    { name: 'Logitech webcam', person: 'Ishita Sen', date: '27 Sep 2026', type: 'Borrowed', status: 'Returned', penalty: '₹90' },
    { name: 'JBL Flip 6', person: 'Kabir Menon', date: '18 Sep 2026', type: 'Borrowed', status: 'Completed', penalty: '—' }
  ]
};

let state = JSON.parse(localStorage.getItem('campusloop_state') || 'null') || seed;
let user = JSON.parse(localStorage.getItem('campusloop_user') || 'null') || { name: 'Aarav Rao', email: 'aarav@campus.edu' };
let authMode = 'login';

function currentUser() {
  return user || { name: 'Guest student', email: 'guest@campus.loop' };
}
function save() {
  localStorage.setItem('campusloop_state', JSON.stringify(state));
  if (user) localStorage.setItem('campusloop_user', JSON.stringify(user));
}
function esc(value) {
  return String(value).replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
}
function icon(kind) {
  return { laptop: '▣', speaker: '◖', camera: '◎', hub: '▦' }[kind] || '▧';
}
function statusClass(status) {
  return status === 'Overdue' ? 'overdue' : status === 'Due soon' ? 'due-soon' : 'on-track';
}
function derivedRental(rental) {
  if (!rental.dueAt || rental.status === 'Returned' || rental.status === 'Pending') return rental;
  const diff = Date.now() - new Date(rental.dueAt).getTime();
  if (diff <= 0) return rental;
  const daysLate = Math.max(1, Math.ceil(diff / 86400000));
  return { ...rental, status: 'Overdue', days: `${daysLate}d overdue`, penalty: `₹${daysLate * 30}` };
}
function addDays(days) {
  const date = new Date(Date.now() + days * 86400000);
  return date.toISOString();
}
function friendlyDue(date) {
  return date.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) + ' · ' + date.toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' });
}

function equipmentCard(item) {
  const action = item.availability === 'Available' ? `<button class="card-action" data-equipment="${item.id}">Request <span>↗</span></button>` : `<span class="card-unavailable">Currently lent out</span>`;
  return `<article class="equipment-card"><div class="equipment-visual ${item.tone}"><span>${icon(item.visual)}</span></div><div class="equipment-card-body"><small>${esc(item.category)} · ${esc(item.owner)}</small><h3>${esc(item.name)}</h3><div class="equipment-meta"><span>${esc(item.meta)}</span><b>${esc(item.rate || 'Free')}</b></div><div class="equipment-card-footer">${action}</div></div></article>`;
}
function renderEquipment() {
  const query = ($('#searchInput')?.value || '').toLowerCase();
  const filter = $('.filter.active')?.dataset.filter || 'All';
  const list = state.equipment.filter((item) => {
    const matchesFilter = filter === 'All' || filter === 'Available' ? (filter === 'All' || item.availability === 'Available') : item.category === filter;
    return matchesFilter && (item.name + item.category + item.owner).toLowerCase().includes(query);
  });
  $('#browseEquipment').innerHTML = list.length ? list.map(equipmentCard).join('') : '<div class="empty" style="grid-column:1/-1"><strong>No gear found</strong>Try a different search or filter.</div>';
  $('#featuredEquipment').innerHTML = state.equipment.slice(0, 4).map(equipmentCard).join('');
}
function renderRequests() {
  $('#requestList').innerHTML = state.requests.length ? state.requests.map((request) => `<article class="request-card"><span class="avatar request-avatar">${esc(request.initials)}</span><div><h3>${esc(request.title)}</h3><p>${esc(request.detail)}</p><div class="request-tags"><span>${esc(request.category)}</span><span>${esc(request.duration)}</span><span>${esc(request.time)}</span></div></div><button class="button button-outline" data-request="${request.id}">Offer gear <span>↗</span></button></article>`).join('') : '<div class="empty"><strong>No open requests</strong>The board is clear for now.</div>';
}
function renderTracking() {
  $('#trackingList').innerHTML = state.rentals.map((rawRental) => {
    const rental = derivedRental(rawRental);
    return `<article class="tracking-card"><div class="track-title"><div class="device-icon">${icon(rental.category === 'Laptop' ? 'laptop' : rental.category === 'Audio' ? 'speaker' : 'hub')}</div><div><strong>${esc(rental.name)}</strong><small>${rental.role === 'borrower' ? 'Borrowed from' : 'Lent to'} ${esc(rental.owner)} · #${esc(rental.id)}</small></div></div><div class="track-col"><small>RETURN BY</small><strong>${esc(rental.due)}</strong></div><div class="track-col"><small>STATUS</small><strong class="${statusClass(rental.status)}">${esc(rental.status)}${rental.penalty !== '—' ? ` · ${esc(rental.penalty)}` : ''}</strong></div><button class="button ${rental.status === 'Overdue' ? 'button-light' : 'button-outline'}" data-rental="${rental.id}">${rental.status === 'Overdue' ? 'Resolve return' : 'View loop'} <span>↗</span></button></article>`;
  }).join('');
}
function renderHistory() {
  $('#historyTable').innerHTML = '<div class="history-row head"><span>EQUIPMENT</span><span>DATE</span><span>ROLE</span><span>OUTCOME</span><span>PENALTY</span></div>' + state.history.map((item) => `<div class="history-row"><div><strong>${esc(item.name)}</strong><small>${esc(item.person)}</small></div><small>${esc(item.date)}</small><small>${esc(item.type)}</small><span class="status-pill ${item.status === 'Active' ? 'due-soon' : 'on-track'}">${esc(item.status)}</span><small>${esc(item.penalty)}</small></div>`).join('');
}
function renderUser() {
  const profile = currentUser();
  const initials = profile.name.split(' ').map((part) => part[0]).join('').slice(0, 2).toUpperCase();
  const first = profile.name.split(' ')[0];
  $('#profileName').textContent = profile.name;
  $('#profileMeta').textContent = profile.email.includes('guest') ? 'Signed out' : 'Student · CSE 2026';
  $('#topProfileName').textContent = first;
  $('#pageTitle').textContent = `Good evening, ${first}`;
  $('#profileAvatar').textContent = initials;
  $('#topAvatar').textContent = initials;
}
function renderAll() {
  renderEquipment(); renderRequests(); renderTracking(); renderHistory(); renderUser(); save();
}
function showView(view) {
  $$('.view').forEach((item) => item.classList.toggle('active', item.id === `view-${view}`));
  $$('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.view === view));
  const labels = { overview: 'Workspace', browse: 'Equipment library', lend: 'Lend equipment', requests: 'Borrow board', tracking: 'Live tracking', history: 'Your loop log' };
  $('#crumbKicker').textContent = labels[view] || 'Workspace';
  $('#pageTitle').textContent = view === 'overview' ? `Good evening, ${currentUser().name.split(' ')[0]}` : labels[view];
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
function toast(text) {
  $('#toastText').textContent = text; $('#toast').classList.add('show'); clearTimeout(window.toastTimer);
  window.toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 3000);
}
function openAuth(mode = 'login') {
  authMode = mode; $('#authOverlay').classList.remove('hidden'); $('#authName').style.display = mode === 'signup' ? 'block' : 'none';
  $('#authTitle').textContent = mode === 'signup' ? 'Join the loop.' : 'Welcome back.';
  $('#authCopy').textContent = mode === 'signup' ? 'Your campus already has useful gear waiting.' : 'Sign in to keep your gear moving.';
  $('#authSubmit').innerHTML = mode === 'signup' ? 'Create account <span>→</span>' : 'Sign in <span>→</span>';
  $('#authSwitch').textContent = mode === 'signup' ? 'Already have an account? Sign in' : 'New here? Create an account';
}
function closeAuth() { $('#authOverlay').classList.add('hidden'); }
function requestRental(item) {
  const due = new Date(Date.now() + 2 * 86400000); due.setHours(18, 0, 0, 0);
  const rental = { id: `CL-${Math.floor(2000 + Math.random() * 7000)}`, name: item.name, category: item.category, owner: item.owner, role: 'borrower', status: 'Pending', due: 'Awaiting approval', dueAt: due.toISOString(), progress: 0, location: 'Pickup point after approval', days: 'Awaiting approval', penalty: '—' };
  state.rentals.unshift(rental); save(); closeDrawer(); renderAll(); showView('tracking'); toast(`Request sent to ${item.owner}.`);
}
function offerGear(request) {
  const item = state.equipment.find((candidate) => candidate.category === request.category && candidate.availability === 'Available') || state.equipment.find((candidate) => candidate.availability === 'Available');
  if (!item) return toast('No available matching gear right now.');
  const rental = { id: `CL-${Math.floor(2000 + Math.random() * 7000)}`, name: item.name, category: item.category, owner: request.person, role: 'lender', status: 'Pending', due: 'Awaiting borrower approval', dueAt: addDays(3), progress: 0, location: 'Arrange pickup after approval', days: 'Pending', penalty: '—' };
  state.rentals.unshift(rental); save(); renderAll(); showView('tracking'); toast(`Offer sent for ${request.title.toLowerCase()}.`);
}
function openDrawer(type, data) {
  let content = '';
  if (type === 'equipment') {
    content = `<p class="eyebrow">AVAILABLE GEAR · ${esc(data.category)}</p><h2>${esc(data.name)}</h2><p>${esc(data.note)}</p><div class="drawer-hero"><small>LENDER</small><strong>${esc(data.owner)}</strong><span>${esc(data.rate)} · Available from ${esc(data.availableFrom || 'this week')}</span></div><div class="drawer-section"><strong>Two-day campus window</strong><small>Request this item now. The lender confirms the handoff before it becomes active.</small></div><div class="drawer-section"><strong>Pickup note</strong><small>Contact details unlock only after approval.</small></div><div class="drawer-actions"><button class="button button-dark" id="confirmRequest">Request this item <span>↗</span></button><button class="button button-outline" id="drawerCloseAction">Keep browsing</button></div>`;
  } else if (type === 'rental') {
    const rental = derivedRental(data);
    const action = rental.status === 'Pending' ? '<button class="button button-dark" id="approveRequest">Approve demo request <span>✓</span></button>' : '<button class="button button-dark" id="confirmReturn">Confirm return <span>✓</span></button>';
    content = `<p class="eyebrow">LOOP #${esc(rental.id)}</p><h2>${esc(rental.name)}</h2><p>${rental.role === 'borrower' ? 'Borrowed from' : 'Lent to'} ${esc(rental.owner)}. Keep the handoff clear and friendly.</p><div class="drawer-hero"><small>RETURN WINDOW</small><strong>${esc(rental.days)}</strong><span>${esc(rental.due)}</span></div><div class="drawer-section"><strong>Pickup / return point</strong><small>${esc(rental.location)}</small></div><div class="drawer-section"><strong>Current status</strong><small class="${statusClass(rental.status)}">${esc(rental.status)}${rental.penalty !== '—' ? ` · penalty ${esc(rental.penalty)}` : ''}</small></div><div class="drawer-actions">${action}<button class="button button-outline" id="drawerCloseAction">Message ${rental.role === 'borrower' ? 'lender' : 'borrower'}</button></div>`;
  } else if (type === 'new-request') {
    content = '<p class="eyebrow">BORROW BOARD</p><h2>Post what you need.</h2><p>Give the campus circle enough detail to make a quick match.</p><form id="requestForm" class="drawer-form"><label>What are you looking for?<input name="title" required placeholder="e.g. Projector for demo day" /></label><label>Category<select name="category"><option>Laptop</option><option>Audio</option><option>Camera</option><option>Accessories</option><option>Other</option></select></label><label>How long?<input name="duration" required placeholder="e.g. 1 day" /></label><label>Details<textarea name="detail" rows="4" placeholder="Pickup location, timing, or context"></textarea></label><button class="button button-dark full" type="submit">Publish request <span>↗</span></button></form>';
  } else {
    const profile = currentUser();
    content = `<p class="eyebrow">ACCOUNT</p><h2>${esc(profile.name)}</h2><p>${esc(profile.email)}<br>${profile.email.includes('guest') ? 'Sign in to manage your loop.' : 'Student · CSE 2026'}</p><div class="drawer-hero"><small>YOUR TRUST SCORE</small><strong>4.9 / 5</strong><span>12 completed loops</span></div><div class="drawer-section"><strong>Privacy by default</strong><small>Your contact details only unlock after a request is accepted.</small></div><div class="drawer-actions"><button class="button button-dark" id="signOut">Sign out</button></div>`;
  }
  $('#drawerContent').innerHTML = content; $('#drawerOverlay').classList.remove('hidden');
  $('#confirmRequest')?.addEventListener('click', () => requestRental(data));
  $('#approveRequest')?.addEventListener('click', () => { data.status = 'On track'; data.days = '2d'; data.due = friendlyDue(new Date(Date.now() + 2 * 86400000)); data.dueAt = addDays(2); data.progress = 8; renderAll(); closeDrawer(); toast('Request approved — the rental is now active.'); });
  $('#confirmReturn')?.addEventListener('click', () => { data.status = 'Returned'; data.penalty = '—'; state.history.unshift({ name: data.name, person: data.owner, date: 'Today', type: data.role === 'borrower' ? 'Borrowed' : 'Lent', status: 'Completed', penalty: '—' }); renderAll(); closeDrawer(); toast('Return confirmed — the loop is complete.'); });
  $('#signOut')?.addEventListener('click', () => { user = { name: 'Guest student', email: 'guest@campus.loop' }; localStorage.removeItem('campusloop_user'); renderUser(); closeDrawer(); openAuth('login'); });
  $('#drawerCloseAction')?.addEventListener('click', closeDrawer);
  $('#requestForm')?.addEventListener('submit', (event) => { event.preventDefault(); const form = new FormData(event.currentTarget); state.requests.unshift({ id: Date.now(), title: form.get('title'), person: currentUser().name, initials: currentUser().name.split(' ').map((part) => part[0]).join('').slice(0, 2).toUpperCase(), time: 'Needed soon', category: form.get('category'), duration: form.get('duration'), detail: form.get('detail') || 'No extra details provided.' }); renderAll(); closeDrawer(); showView('requests'); toast('Request posted — your campus circle can now respond.'); });
}
function closeDrawer() { $('#drawerOverlay').classList.add('hidden'); }

$$('.nav-item,[data-view]').forEach((button) => button.addEventListener('click', (event) => { const view = event.currentTarget.dataset.view; if (view) { showView(view); $('.sidebar').classList.remove('mobile-open'); } }));
$('#searchInput').addEventListener('input', renderEquipment);
$$('.filter').forEach((button) => button.addEventListener('click', () => { $$('.filter').forEach((item) => item.classList.remove('active')); button.classList.add('active'); renderEquipment(); }));
$('#featuredEquipment').addEventListener('click', (event) => { const button = event.target.closest('[data-equipment]'); if (button) { const item = state.equipment.find((candidate) => String(candidate.id) === button.dataset.equipment); if (item) openDrawer('equipment', item); } });
$('#browseEquipment').addEventListener('click', (event) => { const button = event.target.closest('[data-equipment]'); if (button) { const item = state.equipment.find((candidate) => String(candidate.id) === button.dataset.equipment); if (item) openDrawer('equipment', item); } });
$('#lendForm').addEventListener('submit', (event) => { event.preventDefault(); const form = new FormData(event.currentTarget); const category = form.get('category'); state.equipment.unshift({ id: Date.now(), name: form.get('name'), category, owner: currentUser().name, initials: 'AR', visual: category === 'Laptop' ? 'laptop' : category === 'Audio' ? 'speaker' : category === 'Camera' ? 'camera' : 'hub', tone: 'gray', availability: 'Available', meta: `Available from ${form.get('from') || 'today'}`, availableFrom: form.get('from'), note: form.get('note'), rate: form.get('rate') ? `₹${form.get('rate')} / day` : 'Free' }); event.currentTarget.reset(); renderAll(); showView('browse'); toast('Listing published — your gear is now in the loop.'); });
$('#requestList').addEventListener('click', (event) => { const button = event.target.closest('[data-request]'); if (button) { const request = state.requests.find((item) => String(item.id) === button.dataset.request); if (request) offerGear(request); } });
$('#trackingList').addEventListener('click', (event) => { const button = event.target.closest('[data-rental]'); if (button) { const rental = state.rentals.find((item) => item.id === button.dataset.rental); if (rental) openDrawer('rental', rental); } });
$('#authSwitch').addEventListener('click', () => openAuth(authMode === 'login' ? 'signup' : 'login'));
$('#closeAuth').addEventListener('click', closeAuth);
$('#authOverlay').addEventListener('click', (event) => { if (event.target.id === 'authOverlay') closeAuth(); });
$('#authForm').addEventListener('submit', (event) => { event.preventDefault(); user = { name: authMode === 'signup' ? ($('#authName').value || 'New student') : ($('#authEmail').value.split('@')[0].replace(/[._-]/g, ' ') || 'Aarav Rao'), email: $('#authEmail').value }; renderUser(); closeAuth(); toast(authMode === 'signup' ? 'Welcome to the campus circle.' : 'Signed in — your loop is up to date.'); });
$('#profileButton').addEventListener('click', () => openDrawer('profile'));
$('#topProfile').addEventListener('click', () => openDrawer('profile'));
$('#closeDrawer').addEventListener('click', closeDrawer);
$('#drawerOverlay').addEventListener('click', (event) => { if (event.target.id === 'drawerOverlay') closeDrawer(); });
$('#notifyButton').addEventListener('click', () => toast('You have 3 new campus loop updates.'));
$('#postRequest')?.addEventListener('click', () => openDrawer('new-request'));
$('#postRequestSide')?.addEventListener('click', () => openDrawer('new-request'));
$('#mobileMenu')?.addEventListener('click', () => $('.sidebar').classList.toggle('mobile-open'));

renderAll();
const initialView = ({ '/browse': 'browse', '/lend': 'lend', '/requests': 'requests', '/tracking': 'tracking', '/history': 'history' }[window.location.pathname] || 'overview');
showView(initialView);
if (!localStorage.getItem('campusloop_seen')) { setTimeout(() => openAuth('login'), 500); localStorage.setItem('campusloop_seen', '1'); }
