#!/bin/sh
exec gunicorn word_to_wordpressV4:app --bind "0.0.0.0:${PORT:-5000}"
