import '../css/app.css';
import { createInertiaApp } from '@inertiajs/react';

const pages = import.meta.glob('./pages/**/*.jsx');

createInertiaApp({
  title: (title) => (title ? `${title} · Harmonia AI` : 'Harmonia AI'),
  resolve: (name) => pages[`./pages/${name}.jsx`]().then((m) => m.default),
});
