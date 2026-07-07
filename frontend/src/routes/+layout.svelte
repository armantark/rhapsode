<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import favicon from '$lib/assets/favicon.svg';
	import { initApiBase, isTauri } from '$lib/api/platform';

	let { children } = $props();

	let ready = $state(!isTauri());

	onMount(async () => {
		if (!isTauri()) return;
		await initApiBase();
		ready = true;
	});

	const links = [
		{ href: '/', label: 'Library' },
		{ href: '/collections', label: 'Collections' },
		{ href: '/practice', label: 'Practice' },
		{ href: '/review', label: 'Review' },
		{ href: '/settings', label: 'Settings' }
	];

	const isCurrent = (href: string) =>
		href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href);

	// Keyboard shortcuts are the app's fast path but were invisible until
	// discovered by accident; "?" surfaces them from anywhere.
	let shortcutsOpen = $state(false);
	const SHORTCUTS = [
		{ keys: 'Space', what: 'Show the answer to check (recall cards)' },
		{ keys: '1 – 4', what: 'Grade the card: Again · Hard · Good · Easy' },
		{ keys: '⌘Z / Ctrl+Z', what: 'Undo the last graded card' },
		{ keys: 'M', what: 'Drop a line cue while aligning reference audio' },
		{ keys: '?', what: 'Show or hide this overlay' }
	];

	function onWindowKeydown(event: KeyboardEvent) {
		const target = event.target as HTMLElement | null;
		if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
		if (event.key === '?') {
			event.preventDefault();
			shortcutsOpen = !shortcutsOpen;
		} else if (event.key === 'Escape' && shortcutsOpen) {
			shortcutsOpen = false;
		}
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>Rhapsode</title>
</svelte:head>

<div class="shell">
	{#if ready}
		<nav aria-label="Primary">
			<a class="brand" href="/">RHAPSODE</a>
			{#each links as link (link.href)}
				<a href={link.href} aria-current={isCurrent(link.href) ? 'page' : undefined}>{link.label}</a>
			{/each}
			<button
				class="shortcuts-hint"
				title="Keyboard shortcuts (?)"
				aria-label="Keyboard shortcuts"
				onclick={() => (shortcutsOpen = !shortcutsOpen)}
			>?</button>
		</nav>
		<main>{@render children()}</main>
	{:else}
		<p class="boot">Starting Rhapsode…</p>
	{/if}
</div>

{#if shortcutsOpen}
	<!-- Click-outside dismissal; Esc is handled by the window keydown above,
	     so the backdrop needs no keyboard handler of its own. -->
	<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
	<div
		class="shortcuts-backdrop"
		role="presentation"
		onclick={() => (shortcutsOpen = false)}
	>
		<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
		<div
			class="shortcuts card"
			role="dialog"
			aria-modal="true"
			aria-label="Keyboard shortcuts"
			tabindex="-1"
			onclick={(event) => event.stopPropagation()}
		>
			<h2>Keyboard shortcuts</h2>
			<dl>
				{#each SHORTCUTS as shortcut (shortcut.keys)}
					<div class="row">
						<dt><kbd>{shortcut.keys}</kbd></dt>
						<dd>{shortcut.what}</dd>
					</div>
				{/each}
			</dl>
			<p class="muted small">Esc or click outside to close.</p>
		</div>
	</div>
{/if}

<style>
	.shell {
		max-width: 1180px;
		margin: 0 auto;
		padding: 0 24px 80px;
	}

	nav {
		display: flex;
		align-items: baseline;
		gap: 26px;
		padding: 22px 0;
		border-bottom: 1px solid var(--border);
		margin-bottom: 28px;
	}

	.brand {
		font-family: var(--font-mono);
		font-weight: 600;
		letter-spacing: 0.28em;
		color: var(--gold);
		font-size: 1.05rem;
	}

	nav a {
		color: var(--text-dim);
	}

	nav a:hover {
		color: var(--text);
		text-decoration: none;
	}

	nav a[aria-current='page'] {
		color: var(--text);
		border-bottom: 2px solid var(--gold);
		padding-bottom: 4px;
	}

	.shortcuts-hint {
		margin-left: auto;
		font-family: var(--font-mono);
		font-size: 0.8rem;
		width: 26px;
		height: 26px;
		border: 1px solid var(--border);
		border-radius: 50%;
		background: none;
		color: var(--text-dim);
		cursor: pointer;
		align-self: center;
	}

	.shortcuts-hint:hover {
		color: var(--gold);
		border-color: var(--gold);
	}

	main {
		min-height: 60vh;
	}

	.boot {
		padding: 48px 0;
		color: var(--text-dim);
		font-family: var(--font-mono);
		letter-spacing: 0.08em;
	}

	.shortcuts-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(6, 8, 12, 0.72);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
	}

	.shortcuts {
		max-width: 440px;
		width: calc(100% - 48px);
		padding: 22px 26px;
	}

	.shortcuts h2 {
		margin: 0 0 14px;
		font-size: 1.1rem;
	}

	.shortcuts dl {
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 9px;
	}

	.shortcuts .row {
		display: flex;
		align-items: baseline;
		gap: 14px;
	}

	.shortcuts dt {
		min-width: 110px;
	}

	.shortcuts dd {
		margin: 0;
		color: var(--text-dim);
		font-size: 0.88rem;
	}

	.shortcuts .small {
		margin: 14px 0 0;
		font-size: 0.76rem;
	}
</style>
