<script lang="ts">
	import {
		decodeEntities,
		htmlText,
		lex,
		safeHref,
		type Token,
		type Tokens
	} from '#lib/markdown.ts';

	// Rendered Markdown: headings, paragraphs, lists, tables, quotes, code, emphasis and links,
	// built as elements from the tokens. Nothing of the text becomes HTML.
	let { source }: { source: string } = $props();

	const tokens = $derived(lex(source));

	function children(token: Token): Token[] {
		return 'tokens' in token && Array.isArray(token.tokens) ? token.tokens : [];
	}
</script>

{#snippet inline(list: Token[])}
	{#each list as token, index (index)}
		{#if token.type === 'strong'}
			<strong>{@render inline(children(token))}</strong>
		{:else if token.type === 'em'}
			<em>{@render inline(children(token))}</em>
		{:else if token.type === 'del'}
			<del>{@render inline(children(token))}</del>
		{:else if token.type === 'codespan'}
			<code class="rounded bg-muted px-1 font-mono text-[0.9em]">{token.text}</code>
		{:else if token.type === 'br'}
			<br />
		{:else if token.type === 'link'}
			{@const href = safeHref((token as Tokens.Link).href)}
			{#if href}
				<a {href} target="_blank" rel="noopener noreferrer nofollow" class="text-brand underline">
					{@render inline(children(token))}
				</a>
			{:else}
				{@render inline(children(token))}
			{/if}
		{:else if token.type === 'image'}
			<span class="text-muted-foreground">[{decodeEntities((token as Tokens.Image).text)}]</span>
		{:else if token.type === 'html'}
			{htmlText(token as Tokens.HTML)}
		{:else if token.type === 'text' && children(token).length > 0}
			{@render inline(children(token))}
		{:else if 'text' in token}
			{decodeEntities(token.text)}
		{/if}
	{/each}
{/snippet}

{#snippet blocks(list: Token[])}
	{#each list as token, index (index)}
		{#if token.type === 'heading'}
			{@const depth = (token as Tokens.Heading).depth}
			<svelte:element
				this={`h${Math.min(depth + 1, 6)}`}
				class="mt-5 mb-2 max-w-3xl font-semibold first:mt-0 {depth <= 1 ? 'text-xl' : 'text-lg'}"
			>
				{@render inline(children(token))}
			</svelte:element>
		{:else if token.type === 'paragraph'}
			<p class="mb-3 max-w-3xl">{@render inline(children(token))}</p>
		{:else if token.type === 'text'}
			<p class="mb-3 max-w-3xl">
				{@render inline(children(token).length ? children(token) : [token])}
			</p>
		{:else if token.type === 'list'}
			{@const listToken = token as Tokens.List}
			<svelte:element
				this={listToken.ordered ? 'ol' : 'ul'}
				class="mb-3 max-w-3xl pl-6 {listToken.ordered ? 'list-decimal' : 'list-disc'}"
			>
				{#each listToken.items as item, itemIndex (itemIndex)}
					<li>{@render blocks(item.tokens)}</li>
				{/each}
			</svelte:element>
		{:else if token.type === 'table'}
			{@const table = token as Tokens.Table}
			<!-- The whole width; a long cell wraps instead of scrolling a half-page box. -->
			<div class="mb-4">
				<table class="w-full border-collapse text-sm">
					<thead>
						<tr class="border-b text-muted-foreground">
							{#each table.header as cell, cellIndex (cellIndex)}
								<th
									class="px-2 py-1.5 align-bottom font-medium [overflow-wrap:anywhere]"
									style:text-align={cell.align ?? 'left'}
								>
									{@render inline(cell.tokens)}
								</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each table.rows as row, rowIndex (rowIndex)}
							<tr class="border-b border-muted">
								{#each row as cell, cellIndex (cellIndex)}
									<td
										class="px-2 py-1.5 align-top [overflow-wrap:anywhere]"
										style:text-align={cell.align ?? 'left'}
									>
										{@render inline(cell.tokens)}
									</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{:else if token.type === 'blockquote'}
			<blockquote class="mb-3 max-w-3xl border-l-2 pl-4 text-muted-foreground">
				{@render blocks(children(token))}
			</blockquote>
		{:else if token.type === 'code'}
			<!-- Code is literal: the parser escapes nothing in it (a printout keeps its columns). -->
			{@const code = token as Tokens.Code}
			<pre class="mb-3 overflow-x-auto rounded-lg bg-muted p-3 font-mono text-sm">{code.text}</pre>
		{:else if token.type === 'hr'}
			<hr class="my-4" />
		{:else if token.type === 'html'}
			{@const text = htmlText(token as Tokens.HTML)}
			{#if text}<p class="mb-3">{text}</p>{/if}
		{/if}
	{/each}
{/snippet}

<div class="leading-relaxed">{@render blocks(tokens)}</div>
