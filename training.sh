TEXT=data
CUDA_VISIBLE_DEVICES="" python fairseq_cli/train.py \
    data-bin/data.tokenized.en-vi \
    --lr 1e-04 \
    -s en \
    -t vi \
    --optimizer adam \
    --max-tokens 4096 \
    --clip-norm 0.0 \
    --dropout 0.3 \
    --arch transformer \
    --save-dir checkpoints/envi2 \
    --lr-scheduler inverse_sqrt \
    --warmup-init-lr '1e-07' \
    --min-lr '1e-09' \
    --adam-betas "(0.9, 0.998)" \
    --weight-decay 0.0001 \
    --criterion reinforce_shaping \
    --tgtdict_add_sentence_limit_words_after \
    --eval-bleu \
    --eval-bleu-args '{"beam": 4, "max_len_a": 1.2, "max_len_b": 10}' \
    --eval-bleu-detok moses \
    --eval-bleu-remove-bpe \
    --eval-bleu-print-samples \
    --best-checkpoint-metric bleu \
    --maximize-best-checkpoint-metric \
    --patience 3 \
    --batch-size 16
