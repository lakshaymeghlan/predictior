import express from "express";
const app = express();
app.get("/", (req, res) => res.json({ ok: true, msg: "node api placeholder" }));
app.listen(3000, () => console.log("Node API listening on 3000"));
