
DATASET_FOLDER=datasets/de-en_IWSLT2014/data
BASELINE=models/BASELINE_TRANS_convergence_fairseq
MODEL=models/MAX_F_BERT_gumbel-softmax.CONVERGENCE_LR_5e-5
SEED_NUM=seed_1_val_plots
PREP_TEST=dev
EPOCH=_best
for check in checkpoint40.pt checkpoint41.pt checkpoint42.pt checkpoint43.pt checkpoint44.pt checkpoint45.pt checkpoint46.pt checkpoint47.pt checkpoint48.pt checkpoint49.pt checkpoint50.pt; do
CUDA_VISIBLE_DEVICES=0 fairseq-generate data-bin/data.tokenized.en-vi \
               --path checkpoints/envi_baseline/$check \
               --remove-bpe \
               --batch-size 128 --beam 4 --bos [unused0] --pad [PAD] --eos [unused1] --unk [UNK] \
               --tgtdict_add_sentence_limit_words_after \
               --results-path evaluation/envi_baseline/$check
done
