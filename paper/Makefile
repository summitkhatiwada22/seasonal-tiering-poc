# Build the paper: figures (needs the local data, see scripts/paper/figures.py) and the PDF.
PDF = forecasting-vs-reactive-auto-tiering.pdf

all: $(PDF)

figures/fig1_pipeline.pdf figures/fig2_timeline.pdf: figures/fig1_pipeline.tex figures/fig2_timeline.tex figures/standalone.tex preamble-figures.tex
	cd figures && for f in fig1_pipeline fig2_timeline; do \
	  pdflatex -interaction=nonstopmode -jobname=$$f "\def\figfile{$$f}\input{standalone}" >/dev/null && \
	  pdftoppm -png -r 200 -singlefile $$f.pdf $$f; done

$(PDF): main.tex refs.bib preamble-figures.tex figures/*.tex figures/*.pdf
	pdflatex -interaction=nonstopmode main.tex >/dev/null
	bibtex main >/dev/null
	pdflatex -interaction=nonstopmode main.tex >/dev/null
	pdflatex -interaction=nonstopmode main.tex >/dev/null
	cp main.pdf $(PDF)

clean:
	rm -f *.aux *.bbl *.blg *.log *.out figures/*.aux figures/*.log

.PHONY: all clean arxiv

arxiv: $(PDF) ## Source package for arXiv (needs the .bbl from a full build)
	pdflatex -interaction=nonstopmode main.tex >/dev/null
	bibtex main >/dev/null
	tar czf arxiv-source.tar.gz main.tex main.bbl preamble-figures.tex figures/*.tex figures/*.pdf
	$(MAKE) clean
