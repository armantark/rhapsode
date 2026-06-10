<script lang="ts">
	import '../app.css';
	import { page } from '$app/state';
	import favicon from '$lib/assets/favicon.svg';

	let { children } = $props();

	const links = [
		{ href: '/', label: 'Library' },
		{ href: '/practice', label: 'Practice' },
		{ href: '/review', label: 'Review' }
	];

	const isCurrent = (href: string) =>
		href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href);
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>Rhapsode</title>
</svelte:head>

<div class="shell">
	<nav aria-label="Primary">
		<a class="brand" href="/">RHAPSODE</a>
		{#each links as link (link.href)}
			<a href={link.href} aria-current={isCurrent(link.href) ? 'page' : undefined}>{link.label}</a>
		{/each}
	</nav>
	<main>{@render children()}</main>
</div>

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

	main {
		min-height: 60vh;
	}
</style>
