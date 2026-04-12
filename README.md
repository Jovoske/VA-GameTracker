# VA GameTracker

Wildlife camera trap monitoring with AI species recognition (MegaDetector + SpeciesNet) for Piedras Lisas estate, Alatoz.

## Features
- SPYPOINT camera cloud sync
- - MegaDetector v5 animal detection
  - - SpeciesNet species classification
    - - Wild boar size categorization (Big Boar/Sow/Juvenile/Piglet)
      - - Weather & moon phase correlation
        - - Activity pattern predictions
          - - Real-time dashboard
           
            - ## Stack
            - - FastAPI (Python)
              - - SQLite
                - - Open-Meteo weather API
                  - - Vanilla JS frontend
                   
                    - ## Deploy
                    - Docker + Render ready. See `render.yaml`.
