const path = require('path');

module.exports = {
  // Python: ruff lint + format
  '*.py': (files) => {
    const cmds = [
      `ruff check --fix ${files.join(' ')}`,
      `ruff format ${files.join(' ')}`,
    ];
    return cmds;
  },

  // Frontend: eslint --fix on staged files under frontend/
  'frontend/**/*.{ts,tsx,js,jsx,mjs}': (files) => {
    const relFiles = files.map((f) => path.relative(path.join(process.cwd(), 'frontend'), f));
    return [`pnpm --dir frontend exec eslint --fix --no-warn-ignored ${relFiles.join(' ')}`];
  },
};
