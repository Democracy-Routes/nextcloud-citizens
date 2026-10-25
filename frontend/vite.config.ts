import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Builds a single IIFE bundle into the repo's js/ + css/ folders. Nextcloud
// loads js/citizens-main.js and css/citizens-main.css, which the app serves
// itself as a tiny loader stamped with the version (citizens/main.py): the
// real files below carry a .bundle name and a ?v= query, so a browser or the
// AppAPI proxy never keeps the previous build.
export default defineConfig({
	plugins: [vue()],
	build: {
		outDir: '..',
		emptyOutDir: false,
		cssCodeSplit: false,
		rollupOptions: {
			input: 'src/main.ts',
			output: {
				format: 'iife',
				inlineDynamicImports: true,
				entryFileNames: 'js/citizens-main.bundle.js',
				assetFileNames: (assetInfo) =>
					assetInfo.names?.some((n) => n.endsWith('.css'))
						? 'css/citizens-main.bundle.css'
						: 'assets/[name][extname]',
			},
		},
	},
})
