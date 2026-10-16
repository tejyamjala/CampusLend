const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const API = '/api';
let user = null;
let state = { equipment: [], bookings: [], requests: [], communityRequests: [], tools: [], incomingRequests: [], rentals: [] };
let authMode = 'login';

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, { credentials: 'include', headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options });
  const raw = await response.text();
  let data = {};
  try { data = raw ? JSON.parse(raw) : {}; } catch { data = {}; }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status}). Refresh and try again.`);
  return data;
}
function esc(value) { return String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char])); }
function icon(kind) { return { laptop: '▣', speaker: '◖', camera: '◎', hub: '▦' }[kind] || '▧'; }
function visualFor(category) { return category === 'Laptop' ? 'laptop' : category === 'Audio' || category === 'Headphones' ? 'speaker' : category === 'Camera' ? 'camera' : 'hub'; }
function toneFor(category) { return category === 'Laptop' ? 'purple' : category === 'Audio' ? 'blue' : category === 'Camera' ? 'tan' : 'gray'; }
function initials(name) { return (name || 'Student').split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase(); }
function currentUser() { return user || { name: 'Student', email: '' }; }
function formatDay(value) { if (!value) return '—'; return new Date(`${String(value).slice(0, 10)}T12:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }); }
function localDate() { const today = new Date(); return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`; }
function todayLabel() { return new Intl.DateTimeFormat('en-IN', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' }).format(new Date()).replace(',', ' ·').toUpperCase(); }
function toast(message) { $('#toastText').textContent = message; $('#toast').classList.add('show'); clearTimeout(window.toastTimer); window.toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 3200); }
function emptyState(title, copy) { return `<div class="empty" style="grid-column:1/-1"><strong>${esc(title)}</strong>${esc(copy)}</div>`; }

function equipmentCard(device) {
  const requestable = ['available', 'rented'].includes(device.status);
  const action = device.status === 'rented' ? 'Check future dates' : 'Request';
  return `<article class="equipment-card"><div class="equipment-visual ${toneFor(device.category)}"><span>${icon(visualFor(device.category))}</span></div><div class="equipment-card-body"><small>${esc(device.category)} · ${esc(device.owner_name || 'Campus member')}</small><h3>${esc(device.name)}</h3><div class="equipment-meta"><span>${esc(device.condition || 'Condition not added')}</span><b>₹${Number(device.price_per_day || 0)} / day</b></div><div class="equipment-card-footer">${requestable && user ? `<button class="card-action" data-equipment="${device.id}">${action} <span>↗</span></button>` : `<span class="card-unavailable">${user ? 'Currently unavailable' : 'Sign in to request'}</span>`}</div></div></article>`;
}
function renderEquipment() {
  const query = ($('#searchInput')?.value || '').toLowerCase();
  const filter = $('.filter.active')?.dataset.filter || 'All';
  const list = state.equipment.filter((device) => (filter === 'All' || filter === 'Available' || device.category === filter) && (filter !== 'Available' || ['available', 'rented'].includes(device.status)) && `${device.name} ${device.category} ${device.owner_name || ''}`.toLowerCase().includes(query));
  $('#browseEquipment').innerHTML = list.length ? list.map(equipmentCard).join('') : emptyState('No equipment listed yet', user ? 'Be the first student to lend a device to your campus.' : 'Create an account, then sign in to see campus listings.');
  $('#featuredEquipment').innerHTML = list.slice(0, 4).map(equipmentCard).join('') || emptyState('Your campus library is empty', user ? 'List your first device to start the exchange.' : 'Your campus equipment will appear here after students add listings.');
}
function renderRequests() {
  const requests = state.requests || [];
  const rentalMarkup = requests.map((request) => { const isBorrower = Number(request.borrower_id) === Number(user?.id); const contact = isBorrower ? request.owner_email : request.borrower_email; return `<article class="request-card"><span class="avatar request-avatar">${esc(initials(request.borrower_name || request.owner_name))}</span><div><h3>${esc(request.device_name)}</h3><p>${esc(request.message || 'Campus equipment rental request')}</p><div class="request-tags"><span>${esc(request.status)}</span><span>${esc(formatDay(request.pickup_date))} → ${esc(formatDay(request.return_date))}</span><span>${esc(request.pickup_location)}</span></div></div><small>${isBorrower ? 'Your request' : 'Incoming request'}${contact ? `<br>Contact: ${esc(contact)}` : ''}</small></article>`; }).join('');
  const community = state.communityRequests || [];
  const communityMarkup = community.map((post) => `<article class="request-card"><span class="avatar request-avatar">${esc(initials(post.requester_name))}</span><div><h3>${esc(post.title)}</h3><p>${esc(post.detail || 'A student is looking for campus equipment.')}</p><div class="request-tags"><span>${esc(post.category)}</span><span>${esc(post.duration)}</span><span>Open</span></div></div><small>${Number(post.requester_id) === Number(user?.id) ? 'Your post' : esc(post.requester_name)}</small></article>`).join('');
  $('#requestList').innerHTML = rentalMarkup + communityMarkup || emptyState('No rental requests yet', user ? 'Request equipment from Browse gear with pickup dates and a location, or post what you need.' : 'Sign in to see campus requests.');
}
function bookingStatus(booking) { if (booking.status === 'returned') return 'Returned'; if (booking.status === 'pending') return 'Pending'; if (booking.status === 'approved') return 'Approved'; if (booking.return_at && new Date(booking.return_at) < new Date() && booking.status === 'active') return 'Overdue'; return booking.status === 'active' ? 'On track' : booking.status; }
function renderTracking() {
  const bookings = state.bookings || [];
  $('#trackingList').innerHTML = bookings.length ? bookings.map((booking) => { const status = bookingStatus(booking); const role = Number(booking.borrower_id) === Number(user?.id) ? 'Borrowed' : 'Lent'; const action = booking.status === 'approved' ? 'Record handoff' : booking.status === 'active' ? 'Record return' : 'View rental'; return `<article class="tracking-card"><div class="track-title"><div class="device-icon">${icon(visualFor(booking.category))}</div><div><strong>${esc(booking.device_name)}</strong><small>Booking #${esc(booking.id)} · ${role}</small></div></div><div class="track-col"><small>RETURN BY</small><strong>${esc(formatDay(booking.return_date || booking.return_at))}</strong></div><div class="track-col"><small>STATUS</small><strong class="${status === 'Overdue' ? 'overdue' : status === 'On track' ? 'on-track' : ''}">${esc(status)}${booking.late_fee ? ` · ₹${esc(booking.late_fee)}` : ''}</strong></div><button class="button ${status === 'Overdue' ? 'button-light' : 'button-outline'}" data-booking="${booking.id}">${action} <span>↗</span></button></article>`; }).join('') : emptyState('No rentals yet', user ? 'Approved bookings and returns will appear here.' : 'Create an account before starting your first rental.');
}
function renderHistory() {
  const bookings = (state.bookings || []).filter((booking) => booking.status === 'returned');
  if ($('#historyCount')) $('#historyCount').textContent = String(bookings.length).padStart(2, '0');
  $('#historyTable').innerHTML = '<div class="history-row head"><span>EQUIPMENT</span><span>DATE</span><span>ROLE</span><span>OUTCOME</span><span>SAVINGS / FEE</span></div>' + (bookings.length ? bookings.map((booking) => { const borrowed = Number(booking.borrower_id) === Number(user?.id); return `<div class="history-row"><div><strong>${esc(booking.device_name)}</strong><small>Booking #${esc(booking.id)}</small></div><small>${esc(formatDay(booking.return_date || booking.returned_at))}</small><small>${borrowed ? 'Borrowed' : 'Lent'}</small><span class="status-pill on-track">Returned</span><small>${borrowed ? `Saved ₹${esc(booking.savings || 0)}` : `Income ₹${esc(booking.fee || 0)}`}</small></div>`; }).join('') : '<div class="empty"><strong>No completed rentals</strong>Your history is created when real bookings are returned.</div>');
}
function requestActions(request) {
  if (request.status !== 'Pending' || Number(request.owner_id) !== Number(user?.id)) return '';
  return `<div class="tool-request-actions"><button class="button button-dark" data-request-action="approve" data-request-id="${request.id}">Accept</button><button class="button button-outline" data-request-action="reject" data-request-id="${request.id}">Reject</button></div>`;
}
function renderTools() {
  if (!user) { $('#toolsContent').innerHTML = emptyState('Create an account to manage your tools', 'Your private equipment, incoming requests, and rental records appear here.'); return; }
  const tools = state.tools || [];
  if ($('#listingCount')) $('#listingCount').textContent = String(tools.length).padStart(2, '0');
  const incoming = state.incomingRequests || [];
  const rentals = state.rentals || [];
  const listingMarkup = tools.length ? tools.map((tool) => {
    const requests = incoming.filter((request) => Number(request.device_id) === Number(tool.id));
    const hasPending = requests.some((request) => request.status === 'Pending');
    const hasConfirmed = rentals.some((rental) => Number(rental.device_id) === Number(tool.id) && ['approved', 'active'].includes(rental.status));
    const hasHistory = requests.length > 0 || rentals.some((rental) => Number(rental.device_id) === Number(tool.id));
    const lifecycle = tool.status === 'inactive'
      ? `<button class="button button-outline" data-device-action="reactivate" data-device-id="${tool.id}">Reactivate</button>`
      : tool.status === 'available' && !hasPending && !hasConfirmed
        ? `<button class="button button-outline" data-device-action="deactivate" data-device-id="${tool.id}">Unlist</button>`
        : `<span class="listing-note">${hasPending ? 'Resolve pending requests before unlisting.' : 'A confirmed rental currently locks this listing.'}</span>`;
    const deletion = hasHistory
      ? '<span class="listing-note">Listings with history can be unlisted; records are retained.</span>'
      : `<button class="button button-outline" data-device-action="delete" data-device-id="${tool.id}">Delete</button>`;
    const listingActions = `<div class="listing-actions"><button class="button button-outline" data-device-action="edit" data-device-id="${tool.id}">Edit listing</button>${lifecycle}${deletion}</div>`;
    return `<article class="tool-panel panel"><div class="panel-head"><div><p class="eyebrow">YOUR LISTING</p><h3>${esc(tool.name)}</h3><small>${esc(tool.category)} · ${esc(tool.condition || 'Condition not added')} · ₹${Number(tool.price_per_day || 0)} / day</small></div><span class="status-pill ${tool.status === 'available' ? 'on-track' : 'due-soon'}"><i></i>${esc(tool.status)}</span></div>${listingActions}<div class="tool-request-list">${requests.length ? requests.map((request) => `<div class="tool-request"><div><strong>${esc(request.borrower_name)}</strong><small>${esc(formatDay(request.pickup_date))} → ${esc(formatDay(request.return_date))} · ${esc(request.pickup_location)}</small><p>${esc(request.message || 'No message added.')}</p>${request.borrower_email ? `<p>Contact: ${esc(request.borrower_email)}</p>` : ''}</div><div>${requestActions(request)}</div></div>`).join('') : '<div class="tool-empty">No incoming requests for this listing.</div>'}</div></article>`;
  }).join('') : emptyState('You have not listed any equipment', 'Use Lend equipment to add a laptop, speaker, camera, or other gadget.');
  const rentalMarkup = rentals.length ? `<article class="tool-panel panel"><div class="panel-head"><div><p class="eyebrow">APPROVED RENTALS & HISTORY</p><h3>Your rental records</h3><small>Approved handoffs, return state, and lender income.</small></div></div><div class="tool-request-list">${rentals.map((rental) => `<div class="tool-request"><div><strong>${esc(rental.device_name)}</strong><small>${Number(rental.borrower_id) === Number(user.id) ? 'Borrowed' : 'Lent'} · ${esc(formatDay(rental.pickup_date))} → ${esc(formatDay(rental.return_date))} · ${esc(rental.pickup_location || 'Pickup point pending')}</small><p>Status: ${esc(rental.status)} · ${rental.status === 'returned' ? `Savings / income recorded: ₹${esc(Number(rental.borrower_id) === Number(user.id) ? rental.savings : rental.fee)}` : `Fee: ₹${esc(rental.fee || 0)}`}</p></div><button class="button button-outline" data-booking="${rental.id}">View rental <span>↗</span></button></div>`).join('')}</div></article>` : '';
  $('#toolsContent').innerHTML = listingMarkup + rentalMarkup;
}
function renderOverview() {
  const active = state.bookings.filter((booking) => ['approved', 'active'].includes(booking.status));
  const savings = state.bookings.filter((booking) => Number(booking.borrower_id) === Number(user?.id)).reduce((sum, booking) => sum + Number(booking.savings || 0), 0);
  $('#activeCount').textContent = String(active.length).padStart(2, '0');
  $('#savingsCount').textContent = `₹${savings.toLocaleString('en-IN')}`;
  $('#trustCount').textContent = state.bookings.some((booking) => booking.status === 'returned') ? '—' : '—';
  $('#trustCaption').textContent = state.bookings.some((booking) => booking.status === 'returned') ? 'Ratings arrive after returns' : 'No completed loops yet';
  const activePanel = $('.active-rental');
  const activity = $('.activity-panel');
  if (activePanel) activePanel.innerHTML = `<div class="panel-head"><div><p class="eyebrow">YOUR ACTIVE RENTALS</p><h3>${active.length ? `${active.length} active booking${active.length > 1 ? 's' : ''}` : 'Nothing borrowed yet'}</h3></div><span class="status-pill on-track"><i></i>${user ? 'Live' : 'Private'}</span></div><div class="rental-detail"><div class="device-icon laptop-icon">${active.length ? '▣' : '＋'}</div><div><strong>${active.length ? 'Your approved rentals are tracked here.' : 'Start by browsing campus equipment.'}</strong><small>${active.length ? 'Open Track rentals for return details.' : 'No demo rentals or borrowed items are preloaded.'}</small></div></div><div class="rental-footer"><span><small>DATABASE</small><strong>${user ? 'Managed database connected' : 'Waiting for account'}</strong></span><button class="button button-dark" data-view="${user ? 'browse' : 'overview'}">${user ? 'Browse gear' : 'Create account'} <span>↗</span></button></div>`;
  if (activity) activity.innerHTML = `<div class="panel-head"><div><p class="eyebrow">RECENT ACTIVITY</p><h3>${user ? 'Your campus activity' : 'Private workspace'}</h3></div></div><div class="activity-list"><div class="activity-item"><span class="activity-avatar purple">${user ? initials(user.name) : '·'}</span><div><strong>${user ? 'Account ready for your first listing' : 'No account data loaded'}</strong><small>${user ? 'Add a device or request one.' : 'Sign in to connect this workspace.'}</small></div></div></div><button class="button button-outline full" data-view="${user ? 'tools' : 'overview'}">${user ? 'Open Your Tools' : 'Sign in to continue'} <span>→</span></button>`;
}
function renderUser() {
  const profile = currentUser(); const name = profile.name || 'Student';
  $('#profileName').textContent = name; $('#profileMeta').textContent = user ? `${profile.college || 'College student'} · ${user.verified ? 'Verified' : 'Verification pending'}` : 'Create an account to begin'; $('#topProfileName').textContent = name.split(' ')[0]; $('#pageTitle').textContent = user ? `Good evening, ${name.split(' ')[0]}` : 'Your campus equipment exchange'; $('#profileAvatar').textContent = initials(name); $('#topAvatar').textContent = initials(name);
}
function renderAll() { renderEquipment(); renderRequests(); renderTracking(); renderHistory(); renderTools(); renderOverview(); renderUser(); }
function showView(view) { $$('.view').forEach((item) => item.classList.toggle('active', item.id === `view-${view}`)); $$('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.view === view)); const labels = { overview: 'Workspace', browse: 'Equipment library', lend: 'Lend equipment', tools: 'Your tools', requests: 'Borrow requests', tracking: 'Live tracking', history: 'Your loop log' }; $('#crumbKicker').textContent = labels[view] || 'Workspace'; $('#pageTitle').textContent = view === 'overview' ? (user ? `Good evening, ${currentUser().name.split(' ')[0]}` : 'Your campus equipment exchange') : labels[view]; window.scrollTo({ top: 0, behavior: 'smooth' }); }
function openAuth(mode = 'login') { authMode = mode; $('#authOverlay').classList.remove('hidden'); $('#authName').style.display = mode === 'signup' ? 'block' : 'none'; $('#collegeField').style.display = mode === 'signup' ? 'grid' : 'none'; $('#authTitle').textContent = mode === 'signup' ? 'Create your account.' : 'Sign in to your campus.'; $('#authCopy').textContent = mode === 'signup' ? 'Use your own details. Nothing is preloaded.' : 'Your listings, bookings, and history live in the database.'; $('#authSubmit').innerHTML = mode === 'signup' ? 'Create account <span>→</span>' : 'Sign in <span>→</span>'; $('#authSwitch').textContent = mode === 'signup' ? 'Already have an account? Sign in' : 'New here? Create an account'; }
function closeAuth() { $('#authOverlay').classList.add('hidden'); }
function closeDrawer() { $('#drawerOverlay').classList.add('hidden'); }
async function loadData() {
  if (!user) { state = { equipment: [], bookings: [], requests: [], communityRequests: [], tools: [], incomingRequests: [], rentals: [] }; renderAll(); return; }
  const [devices, bookings, requests, tools] = await Promise.all([api('/devices'), api('/bookings'), api('/requests'), api('/tools')]);
  state = { equipment: devices.devices || [], bookings: bookings.bookings || [], requests: requests.requests || [], communityRequests: requests.community_requests || [], tools: tools.tools || [], incomingRequests: tools.incoming_requests || [], rentals: tools.rentals || [] };
  renderAll();
}
function openDrawer(type, data) {
  let content = '';
  if (type === 'equipment') content = `<p class="eyebrow">${data.status === 'rented' ? 'CHECK FUTURE AVAILABILITY' : 'AVAILABLE GEAR'} · ${esc(data.category)}</p><h2>${esc(data.name)}</h2><p>${esc(data.condition || 'Condition details supplied by the owner.')}${data.status === 'rented' ? ' Existing rental dates are blocked; choose a free future window.' : ''}</p><div class="drawer-hero"><small>LENDER</small><strong>${esc(data.owner_name || 'Campus member')}</strong><span>₹${Number(data.price_per_day || 0)} / day</span></div><form id="bookingForm" class="drawer-form"><label>Pickup date<input name="pickup_date" type="date" min="${localDate()}" required /></label><label>Return date<input name="return_date" type="date" min="${localDate()}" required /></label><label>Pickup location<input name="pickup_location" required maxlength="255" placeholder="Library desk, hostel lobby, lab..." /></label><label>Message to owner<textarea name="message" rows="3" maxlength="2000" placeholder="Add timing or handover details"></textarea></label><button class="button button-dark full" type="submit">Send request for approval <span>↗</span></button></form>`;
  else if (type === 'new-request') content = '<p class="eyebrow">BORROW BOARD</p><h2>Post what you need.</h2><form id="requestForm" class="drawer-form"><label>What are you looking for?<input name="title" required placeholder="e.g. Projector for demo day" /></label><label>Category<select name="category"><option>Laptop</option><option>Audio</option><option>Camera</option><option>Accessories</option><option>Other</option></select></label><label>How long?<input name="duration" required placeholder="e.g. 1 day" /></label><label>Details<textarea name="detail" rows="4" placeholder="Tell students what would help"></textarea></label><button class="button button-dark full" type="submit">Publish request <span>↗</span></button></form>';
  else if (type === 'edit-device') content = `<p class="eyebrow">YOUR LISTING · EDIT</p><h2>${esc(data.name)}</h2><form id="editDeviceForm" class="drawer-form"><label>Equipment name<input name="name" required maxlength="255" value="${esc(data.name)}" /></label><label>Category<input name="category" required maxlength="80" value="${esc(data.category)}" /></label><label>Condition<input name="condition" maxlength="255" value="${esc(data.condition || 'Good condition')}" /></label><label>Daily rate<input name="price_per_day" type="number" min="0" step="0.01" value="${Number(data.price_per_day || 0)}" /></label><label>Available from<input name="available_from" type="date" value="${esc(String(data.available_from || '').slice(0, 10))}" /></label><label>Available through<input name="available_to" type="date" value="${esc(String(data.available_to || '').slice(0, 10))}" /></label><button class="button button-dark full" type="submit">Save listing changes <span>✓</span></button></form>`;
  else if (type === 'booking') { const isBorrower = Number(data.borrower_id) === Number(user?.id); const paymentAction = isBorrower && ['approved', 'active'].includes(data.status) ? '<button class="button button-dark" id="simulatePayment">Record demo payment <span>✓</span></button>' : ''; const rentalAction = data.status === 'approved' ? '<button class="button button-outline" id="pickupBooking">Record handoff</button>' : data.status === 'active' ? '<button class="button button-outline" id="returnBooking">Record return</button>' : ''; content = `<p class="eyebrow">BOOKING #${esc(data.id)} · ${esc(data.status)}</p><h2>${esc(data.device_name)}</h2><p>${esc(data.reason || 'Campus equipment rental')}</p><div class="drawer-hero"><small>TOTAL RENTAL FEE</small><strong>₹${esc(data.fee || 0)}</strong><span>${esc(data.payment_status || 'unpaid')}</span></div><p class="demo-note">DEMO / SIMULATED PAYMENT — no real money is transferred.</p><div class="drawer-actions">${paymentAction}${rentalAction}</div>`; }
  else { const profile = currentUser(); content = `<p class="eyebrow">ACCOUNT</p><h2>${esc(profile.name)}</h2><p>${esc(profile.email || '')}<br>${user ? esc(profile.college || 'College student') : 'Create your account to connect data.'}</p><div class="drawer-section"><strong>Managed database workspace</strong><small>Only your own account, listings, requests, and rentals appear here.</small></div><div class="drawer-actions"><button class="button button-dark" id="signOut">${user ? 'Sign out' : 'Close'}</button></div>`; }
  $('#drawerContent').innerHTML = content; $('#drawerOverlay').classList.remove('hidden');
  $('#bookingForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const pickup = form.get('pickup_date'); const returnDate = form.get('return_date');
    if (returnDate < pickup) { toast('Return date cannot be before pickup date.'); return; }
    const submit = formElement.querySelector('button[type="submit"]');
    if (submit.disabled) return;
    submit.disabled = true; submit.textContent = 'Sending request…';
    try { await api('/rental-requests', { method: 'POST', body: JSON.stringify({ device_id: data.id, pickup_date: pickup, return_date: returnDate, pickup_location: form.get('pickup_location'), message: form.get('message') }) }); closeDrawer(); showView('requests'); toast('Request sent. The equipment owner must approve it.'); try { await loadData(); } catch { toast('Your request is saved. Refresh the page to update the request list.'); } }
    catch (error) { toast(error.message); }
    finally { if (submit.isConnected) { submit.disabled = false; submit.textContent = 'Send request for approval ↗'; } }
  });
  const bookingForm = $('#bookingForm');
  if (bookingForm) {
    const pickupInput = bookingForm.elements.namedItem('pickup_date');
    const returnInput = bookingForm.elements.namedItem('return_date');
    pickupInput.addEventListener('change', () => { returnInput.min = pickupInput.value || localDate(); if (returnInput.value && returnInput.value < returnInput.min) returnInput.value = ''; });
  }
  $('#editDeviceForm')?.addEventListener('submit', async (event) => {
    event.preventDefault(); const formElement = event.currentTarget; const submit = formElement.querySelector('button[type="submit"]');
    if (submit.disabled) return;
    submit.disabled = true;
    const form = new FormData(formElement);
    try {
      await api(`/devices/${data.id}`, { method: 'PUT', body: JSON.stringify({ name: form.get('name'), category: form.get('category'), condition: form.get('condition'), price_per_day: form.get('price_per_day'), available_from: form.get('available_from'), available_to: form.get('available_to') }) });
      closeDrawer(); toast('Listing changes saved.');
      try { await loadData(); } catch { toast('Your changes are saved. Refresh the page to update Your Tools.'); }
    } catch (error) { toast(error.message); }
    finally { if (submit.isConnected) submit.disabled = false; }
  });
  $('#requestForm')?.addEventListener('submit', async (event) => {
    event.preventDefault(); const formElement = event.currentTarget; const submit = formElement.querySelector('button[type="submit"]');
    if (submit.disabled) return;
    submit.disabled = true;
    try { await api('/requests', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(formElement).entries())) }); closeDrawer(); showView('requests'); toast('Your campus request is saved.'); try { await loadData(); } catch { toast('Your request is saved. Refresh the page to update the request board.'); } }
    catch (error) { toast(error.message); }
    finally { if (submit.isConnected) submit.disabled = false; }
  });
  $('#simulatePayment')?.addEventListener('click', async () => { try { await api(`/bookings/${data.id}/simulate-payment`, { method: 'POST' }); closeDrawer(); await loadData(); toast('DEMO / SIMULATED payment recorded.'); } catch (error) { toast(error.message); } });
  $('#pickupBooking')?.addEventListener('click', async () => { try { await api(`/bookings/${data.id}/pickup`, { method: 'POST' }); closeDrawer(); await loadData(); toast('Handoff recorded. The rental is now active.'); } catch (error) { toast(error.message); } });
  $('#returnBooking')?.addEventListener('click', async () => { try { const result = await api(`/bookings/${data.id}/return`, { method: 'POST' }); closeDrawer(); await loadData(); toast(result.late_fee ? `Return recorded. Late fee: ₹${result.late_fee}.` : `Return recorded. Borrower savings: ₹${result.savings}.`); } catch (error) { toast(error.message); } });
  $('#signOut')?.addEventListener('click', async () => { if (user) await api('/auth/logout', { method: 'POST' }); user = null; closeDrawer(); renderAll(); openAuth('login'); });
}

document.addEventListener('click', (event) => { const button = event.target.closest('[data-view]'); if (!button) return; const view = button.dataset.view; if (view) { showView(view); $('.sidebar').classList.remove('mobile-open'); } });
$('#searchInput').addEventListener('input', renderEquipment); $$('.filter').forEach((button) => button.addEventListener('click', () => { $$('.filter').forEach((item) => item.classList.remove('active')); button.classList.add('active'); renderEquipment(); }));
function openEquipmentFrom(event) { const button = event.target.closest('[data-equipment]'); if (button) { const item = state.equipment.find((candidate) => String(candidate.id) === button.dataset.equipment); if (item) openDrawer('equipment', item); } }
$('#featuredEquipment').addEventListener('click', openEquipmentFrom); $('#browseEquipment').addEventListener('click', openEquipmentFrom);
$('#lendForm').addEventListener('submit', async (event) => { event.preventDefault(); const formElement = event.currentTarget; const submit = formElement.querySelector('button[type="submit"]'); if (submit.disabled) return; submit.disabled = true; const form = new FormData(formElement); try { await api('/devices', { method: 'POST', body: JSON.stringify({ name: form.get('name'), category: form.get('category'), condition: form.get('note') || 'Good condition', price_per_day: Number(form.get('rate') || 0), available_from: form.get('from'), available_to: form.get('to') }) }); formElement.reset(); const availableFrom = $('#availableFrom'); const availableTo = $('#availableTo'); availableFrom.min = localDate(); availableFrom.value = localDate(); availableTo.min = localDate(); availableTo.value = ''; showView('tools'); toast('Your listing is saved to the database.'); try { await loadData(); } catch { toast('Your listing is saved. Refresh the page to update Your Tools.'); } } catch (error) { toast(error.message); } finally { submit.disabled = false; } });
$('#toolsContent').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-device-action]');
  if (!button) return;
  const deviceId = button.dataset.deviceId;
  const action = button.dataset.deviceAction;
  const device = state.tools.find((item) => String(item.id) === String(deviceId));
  if (!device) return;
  if (action === 'edit') { openDrawer('edit-device', device); return; }
  if (action === 'delete' && !window.confirm(`Delete “${device.name}”? This permanently removes the unused listing. Listings with request or rental history cannot be deleted.`)) return;
  button.disabled = true;
  try {
    if (action === 'delete') await api(`/devices/${deviceId}`, { method: 'DELETE' });
    else await api(`/devices/${deviceId}/${action}`, { method: 'POST' });
    toast(action === 'delete' ? 'Unused listing deleted.' : action === 'deactivate' ? 'Listing unlisted; its history is preserved.' : 'Listing is available again.');
    try { await loadData(); } catch { toast('The change is saved. Refresh the page to update Your Tools.'); }
  } catch (error) { toast(error.message); }
  finally { if (button.isConnected) button.disabled = false; }
});
$('#toolsContent').addEventListener('click', async (event) => { const bookingButton = event.target.closest('[data-booking]'); if (bookingButton) { const booking = state.rentals.find((item) => String(item.id) === bookingButton.dataset.booking) || state.bookings.find((item) => String(item.id) === bookingButton.dataset.booking); if (booking) openDrawer('booking', booking); return; } const button = event.target.closest('[data-request-action]'); if (!button) return; try { await api(`/rental-requests/${button.dataset.requestId}/${button.dataset.requestAction}`, { method: 'POST' }); await loadData(); toast(button.dataset.requestAction === 'approve' ? 'Request accepted and rental created.' : 'Request rejected.'); } catch (error) { toast(error.message); } });
$('#requestList').addEventListener('click', (event) => { const button = event.target.closest('[data-equipment]'); if (button) openEquipmentFrom(event); });
$('#trackingList').addEventListener('click', (event) => { const button = event.target.closest('[data-booking]'); if (button) { const booking = state.bookings.find((item) => String(item.id) === button.dataset.booking); if (booking) openDrawer('booking', booking); } });
$('#authSwitch').addEventListener('click', () => openAuth(authMode === 'login' ? 'signup' : 'login')); $('#closeAuth').addEventListener('click', closeAuth); $('#authOverlay').addEventListener('click', (event) => { if (event.target.id === 'authOverlay') closeAuth(); });
$('#authForm').addEventListener('submit', async (event) => { event.preventDefault(); const formElement = event.currentTarget; const submit = $('#authSubmit'); if (submit.disabled) return; submit.disabled = true; const payload = { name: $('#authName').value, email: $('#authEmail').value, password: $('#authPassword').value, college: $('#authCollege').value }; try { const result = await api(authMode === 'signup' ? '/auth/register' : '/auth/login', { method: 'POST', body: JSON.stringify(payload) }); user = result.user; formElement.reset(); closeAuth(); await loadData(); toast(authMode === 'signup' ? 'Account created. Your workspace is ready.' : 'Signed in — your database workspace is connected.'); } catch (error) { toast(error.message); } finally { submit.disabled = false; } });
$('#profileButton').addEventListener('click', () => openDrawer('profile')); $('#topProfile').addEventListener('click', () => openDrawer('profile')); $('#closeDrawer').addEventListener('click', closeDrawer); $('#drawerOverlay').addEventListener('click', (event) => { if (event.target.id === 'drawerOverlay') closeDrawer(); }); $('#notifyButton').addEventListener('click', () => toast(user ? 'New approvals and rental updates will appear here.' : 'Sign in to receive campus notifications.')); $('#postRequest')?.addEventListener('click', () => user ? openDrawer('new-request') : openAuth('login')); $('#postRequestSide')?.addEventListener('click', () => user ? openDrawer('new-request') : openAuth('login')); $('#mobileMenu')?.addEventListener('click', () => $('.sidebar').classList.toggle('mobile-open'));

(function initializeDateFields() { const today = localDate(); $('#todayLabel').textContent = todayLabel(); const availableFrom = $('#availableFrom'); const availableTo = $('#availableTo'); availableFrom.min = today; availableFrom.value = today; availableTo.min = today; availableFrom.addEventListener('change', () => { availableTo.min = availableFrom.value || today; if (availableTo.value && availableTo.value < availableTo.min) availableTo.value = ''; }); })();
(async function boot() { try { const session = await api('/auth/me'); user = session.user || null; } catch { user = null; } try { await loadData(); } catch (error) { toast(error.message); renderAll(); } const route = ({ '/browse': 'browse', '/lend': 'lend', '/tools': 'tools', '/requests': 'requests', '/tracking': 'tracking', '/history': 'history' }[window.location.pathname] || 'overview'); showView(route); if (window.location.pathname === '/login') openAuth('login'); else if (window.location.pathname === '/signup' || !user) openAuth('signup'); })();
