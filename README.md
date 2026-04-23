# Dome Animatic Addon

A Blender addon for creating animatic sequences with dome-based live preview and collage manipulation.

## Installation

1. Install the addon in Blender by navigating to `Edit > Preferences > Add-ons`
2. Click "Install" and select the addon folder
3. Enable the addon in the search results

## Project Structure

```
DomeAnimaticAddon/
├── addons/
│   └── DomeAnimatic/          # Main addon source code
│       ├── __init__.py        # Addon entry point
│       ├── operators.py       # Main operators
│       ├── panels.py          # UI panels
│       ├── properties.py      # Custom properties
│       ├── handlers.py        # Event handlers
│       └── ...                # Other modules
├── README.md                  # This file
├── requirements.txt           # Python dependencies
└── install.py                 # Installation script
```

## Documentation

See `addons/DomeAnimatic/DomeAnimatic_Documentation.md` for detailed documentation.

## Development

### Setting up for development

```bash
# Clone or navigate to project
cd DomeAnimaticAddon

# Install dependencies
pip install -r requirements.txt

# Run installation script
python install.py
```

### Git Workflow

This project uses Git for version control. When working across multiple computers:

1. **Pull changes** before starting work: `git pull`
2. **Make changes** and test locally
3. **Commit** with clear messages: `git commit -m "Description of changes"`
4. **Push** to remote: `git push`

### Using with Git Fork

You can use Git Fork GUI for visual git operations while Claude handles automation:
- Git Fork will see all commits and branches that Claude creates
- Both tools work on the same repository

## Contributing

Please follow these guidelines:
- Create descriptive commit messages
- Test changes in Blender before committing
- Keep code well-documented

## Multi-Computer Setup

Working from multiple computers:
- Clone the repository on each computer
- Keep code in Git, assets can be on Google Drive
- Use relative paths for asset references
- Pull before starting, push when done

## License

[Add license information here]
