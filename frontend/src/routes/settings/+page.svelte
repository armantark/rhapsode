<script lang="ts">
	import Skeleton from '$lib/components/Skeleton.svelte';
	import { onMount } from 'svelte';
	import { api } from '$lib/api/client';
	import type { SystemStatus } from '$lib/api/types';
	import { isSoundEnabled, setSoundEnabled } from '$lib/utils/feedback';

	let status: SystemStatus | null = $state(null);
	let error = $state('');
	let loading = $state(true);

	// Gemini key: stored as an app setting (env stays the fallback), entered
	// masked, never echoed back — only "configured" state is shown.
	let keyDraft = $state('');
	let savingKey = $state(false);
	let keyNotice = $state('');

	// Practice defaults live in localStorage (per-browser, like the practice
	// page toggles) — surfaced here so they're discoverable in one place.
	const MIC_KEY = 'rhapsode.micEnabled';
	let soundOn = $state(true);
	let micOn = $state(false);

	const lastBackupLabel = $derived.by(() => {
		const snapshot = status as SystemStatus | null;
		if (!snapshot?.last_backup_at) return 'never';
		const hours = (Date.now() - new Date(snapshot.last_backup_at).getTime()) / 3_600_000;
		if (hours < 1) return 'less than an hour ago';
		if (hours < 48) return `${Math.round(hours)}h ago`;
		return `${Math.round(hours / 24)} days ago`;
	});

	onMount(async () => {
		soundOn = isSoundEnabled();
		micOn = localStorage.getItem(MIC_KEY) === 'true';
		try {
			status = await api.systemStatus();
		} catch (cause) {
			error = `Could not load system status: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			loading = false;
		}
	});

	async function saveKey() {
		savingKey = true;
		keyNotice = '';
		error = '';
		try {
			await api.putSetting('gemini_api_key', keyDraft.trim());
			status = await api.systemStatus();
			keyNotice = keyDraft.trim()
				? 'Key saved — prep drafting will use it from the next request.'
				: 'Key cleared — the GEMINI_API_KEY environment variable (if any) applies.';
			keyDraft = '';
		} catch (cause) {
			error = `Could not save the key: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			savingKey = false;
		}
	}

	function toggleSoundDefault() {
		soundOn = !soundOn;
		setSoundEnabled(soundOn);
	}

	function toggleMicDefault() {
		micOn = !micOn;
		localStorage.setItem(MIC_KEY, String(micOn));
	}
</script>

<svelte:head><title>Settings · Rhapsode</title></svelte:head>

<header class="head">
	<div>
		<span class="eyebrow">Configuration</span>
		<h1>Settings</h1>
	</div>
</header>

{#if error}<p class="error-banner" role="alert">{error}</p>{/if}

{#if loading}
	<Skeleton rows={4} card />
{:else if status}
	<div class="stack">
		<section class="card">
			<span class="eyebrow">Data safety</span>
			<p>
				Snapshots land in <code>{status.backup_dir}</code> — last backup
				<strong>{lastBackupLabel}</strong>. A snapshot is taken at startup (once per day) and
				before every migration.
			</p>
			<p class="muted small">
				Point <code>RHAPSODE_BACKUP_DIR</code> at a synced folder (e.g. iCloud) so a lost machine
				isn't lost practice history.
			</p>
		</section>

		<section class="card">
			<span class="eyebrow">Scheduler</span>
			<p>
				Retention target <strong>{Math.round(status.desired_retention * 100)}%</strong> ·
				{#if status.fsrs_personal_parameters}
					<strong>personal FSRS weights active</strong> — fitted from your own review history.
				{:else}
					population-default FSRS weights. Once a few hundred reviews are logged, run
					<code>uv run --extra optimizer python scripts/optimize_fsrs.py</code> from
					<code>backend/</code> to fit personal weights.
				{/if}
			</p>
		</section>

		<section class="card">
			<span class="eyebrow">Prep assistant</span>
			<p>
				Gemini key:
				{#if status.gemini_key_configured}
					<strong class="ok">configured</strong>
				{:else}
					<strong class="warn">not configured</strong> — prep drafting (cues, glosses,
					translations) is unavailable until one is added.
				{/if}
			</p>
			<div class="key-row">
				<input
					type="password"
					bind:value={keyDraft}
					placeholder="Paste a Gemini API key (blank to clear)"
					aria-label="Gemini API key"
					autocomplete="off"
				/>
				<button class="primary" onclick={saveKey} disabled={savingKey}>
					{savingKey ? 'Saving…' : 'Save key'}
				</button>
			</div>
			{#if keyNotice}<p class="muted small">{keyNotice}</p>{/if}
			<p class="muted small">
				The key only ever drafts prep content; the practice loop never calls the LLM.
			</p>
		</section>

		<section class="card">
			<span class="eyebrow">Practice defaults</span>
			<div class="toggles">
				<button class:active={soundOn} aria-pressed={soundOn} onclick={toggleSoundDefault}>
					{soundOn ? '🔊 Sound on' : '🔇 Sound off'}
				</button>
				<button class:active={micOn} aria-pressed={micOn} onclick={toggleMicDefault}>
					{micOn ? '🎙 Recording enabled' : '🎙 Recording off'}
				</button>
			</div>
			<p class="muted small">
				Per-browser defaults; both can also be toggled on the practice page itself.
			</p>
		</section>
	</div>
{/if}

<style>
	.head {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		margin-bottom: 20px;
	}

	h1 {
		margin: 6px 0 0;
	}

	.stack {
		display: flex;
		flex-direction: column;
		gap: 16px;
		max-width: 720px;
	}

	.card p {
		margin: 10px 0 0;
	}

	code {
		font-family: var(--font-mono);
		font-size: 0.82em;
		color: var(--gold);
	}

	.ok {
		color: var(--green, #4ade80);
	}

	.warn {
		color: var(--gold);
	}

	.key-row {
		display: flex;
		gap: 10px;
		margin-top: 12px;
		flex-wrap: wrap;
	}

	.key-row input {
		flex: 1;
		min-width: 240px;
	}

	.toggles {
		display: flex;
		gap: 10px;
		margin-top: 12px;
		flex-wrap: wrap;
	}

	.toggles button.active {
		border-color: var(--gold);
		color: var(--gold);
	}

	.small {
		font-size: 0.82rem;
	}
</style>
