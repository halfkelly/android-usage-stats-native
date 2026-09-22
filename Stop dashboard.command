#!/bin/bash
pkill -f "wellbeing serve" 2>/dev/null && echo "" && echo "  Dashboard stopped." || echo "" && echo "  It wasn't running."
echo ""
read -n 1 -s -r -p "  Press any key to close..."
