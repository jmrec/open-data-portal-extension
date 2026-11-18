# Alias to `just -l`
default:
    just -l

# Run library skills
library-skills *flags:
    uvx library-skills {{ flags }}

# Show project file structure
tree:
    tree --dirsfirst -I ".agents|.cache|.venv|site" .
